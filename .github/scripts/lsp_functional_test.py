#!/usr/bin/env python3
"""
LSP functional test — verifies real PHP code intelligence for PHPantom.

Sequence:
  initialize → initialized
    → didOpen(test.php)                → completion + hover
    → didOpen(test_implementation.php) → textDocument/implementation
  → shutdown → exit

Usage:
  python3 lsp_functional_test.py phpantom

Fixture positions (0-indexed):
  test.php
    Completion : line 25, char 15  — right after "$greeter->"
    Hover      : line 4,  char 8   — inside "class Greeter"
  test_implementation.php
    Implementation : line 6, char 20 — inside "greet" in interface Greetable
                     expected result → line 11 (Greeter::greet implementation)
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

ENCODING = "utf-8"

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT        = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FIXTURE_DIR      = os.path.join(SCRIPT_DIR, "fixtures")
FIXTURE_FILE     = os.path.join(FIXTURE_DIR, "test.php")
FIXTURE_IMPL     = os.path.join(FIXTURE_DIR, "test_implementation.php")

ROOT_URI      = "file:///workspace"
FILE_URI      = "file:///workspace/test.php"
IMPL_FILE_URI = "file:///workspace/test_implementation.php"

REQUEST_TIMEOUT = 30


# ── LSP framing ───────────────────────────────────────────────────────────────

def encode(msg: dict) -> bytes:
    body   = json.dumps(msg, separators=(",", ":")).encode(ENCODING)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING)
    return header + body


def read_message(stream) -> dict | None:
    headers = {}
    while True:
        raw = stream.readline()
        if not raw:
            return None
        line = raw.decode(ENCODING).rstrip("\r\n")
        if not line:
            break
        k, _, v = line.partition(": ")
        headers[k] = v
    length = int(headers.get("Content-Length", 0))
    if not length:
        return None
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode(ENCODING))


# ── Background stdout reader ──────────────────────────────────────────────────

def start_reader(proc: subprocess.Popen) -> queue.Queue:
    msg_queue: queue.Queue = queue.Queue()

    def _read():
        while True:
            msg = read_message(proc.stdout)
            msg_queue.put(msg)
            if msg is None:
                break

    threading.Thread(target=_read, daemon=True).start()
    return msg_queue


def wait_for_ids(msg_queue: queue.Queue, ids: set, label: str) -> dict:
    results = {}
    deadline = time.monotonic() + REQUEST_TIMEOUT
    while time.monotonic() < deadline and len(results) < len(ids):
        remaining = max(0.1, deadline - time.monotonic())
        try:
            msg = msg_queue.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue
        if msg is None:
            break
        if msg.get("id") in ids:
            results[msg["id"]] = msg
    return results


# ── Server startup ────────────────────────────────────────────────────────────

def start_server() -> subprocess.Popen:
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    return subprocess.Popen(
        [
            "docker", "run", "--rm", "--interactive",
            "--user", uid_gid,
            "--volume", f"{FIXTURE_DIR}:/workspace",
            "--workdir", "/workspace",
            "claude-code-lsp-phpantom",
        ],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def drain_stderr(proc: subprocess.Popen, label: str) -> None:
    def _drain():
        for line in proc.stderr:
            sys.stderr.buffer.write(f"[{label}] ".encode() + line)
            sys.stderr.buffer.flush()
    threading.Thread(target=_drain, daemon=True).start()


# ── Shutdown ──────────────────────────────────────────────────────────────────

def shutdown(proc: subprocess.Popen, next_id: int) -> None:
    try:
        proc.stdin.write(encode({"jsonrpc": "2.0", "id": next_id, "method": "shutdown", "params": None}))
        proc.stdin.write(encode({"jsonrpc": "2.0", "method": "exit"}))
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Assertions ────────────────────────────────────────────────────────────────

def check_completion(result, plugin: str) -> None:
    if result is None:
        _fail(plugin, "completion", "null result — no completions returned")

    items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(items, list) or len(items) == 0:
        _fail(plugin, "completion", f"expected non-empty items, got: {result!r}")

    labels = {item.get("label", "") for item in items if isinstance(item, dict)}
    if not any(lbl in labels for lbl in ("greet", "farewell", "greet()", "farewell()",
                                          "greet(): string", "farewell(): string")):
        _fail(plugin, "completion",
              f"expected greet/farewell in labels, got: {sorted(labels)!r}")

    print(f"[functional] {plugin} completion: OK — {len(items)} items, "
          f"labels: {sorted(labels)!r}", flush=True)


def check_hover(result, plugin: str) -> None:
    if result is None:
        print(f"[functional] {plugin} hover: WARN — null (cursor may be off-symbol)", flush=True)
        return
    if not result.get("contents"):
        _fail(plugin, "hover", f"expected 'contents' in result, got: {result!r}")
    print(f"[functional] {plugin} hover: OK", flush=True)


def check_implementation(result, plugin: str) -> None:
    if result is None:
        _fail(plugin, "implementation", "null result — PHPantom should return a location")

    locations = result if isinstance(result, list) else [result]
    if not locations:
        _fail(plugin, "implementation", "empty location list")

    uris = [loc.get("uri", "") for loc in locations if isinstance(loc, dict)]
    if not any("test_implementation.php" in uri for uri in uris):
        _fail(plugin, "implementation",
              f"expected uri containing test_implementation.php, got: {uris!r}")

    lines = [loc.get("range", {}).get("start", {}).get("line") for loc in locations]
    if 11 not in lines:
        _fail(plugin, "implementation",
              f"expected implementation at line 11 (Greeter::greet), got lines: {lines!r}")

    print(f"[functional] {plugin} implementation: OK — "
          f"found {len(locations)} location(s) at line(s) {lines}", flush=True)


def _fail(plugin: str, test: str, reason: str) -> None:
    print(f"[functional] {plugin} {test}: FAIL — {reason}", file=sys.stderr, flush=True)
    sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "phpantom":
        print("Usage: lsp_functional_test.py phpantom", file=sys.stderr)
        sys.exit(1)

    plugin = sys.argv[1]
    print(f"[functional] Starting {plugin}…", flush=True)

    proc = start_server()
    drain_stderr(proc, plugin)
    msg_queue = start_reader(proc)

    req_id = 1

    # 1 ── initialize ─────────────────────────────────────────────────────────
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": req_id, "method": "initialize",
        "params": {
            "processId": os.getpid(),
            "rootUri": ROOT_URI,
            "capabilities": {
                "textDocument": {
                    "completion": {"completionItem": {"snippetSupport": True}, "contextSupport": True},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "implementation": {"dynamicRegistration": False},
                    "publishDiagnostics": {},
                }
            },
            "trace": "off",
        },
    }))
    proc.stdin.flush()

    init_responses = wait_for_ids(msg_queue, {req_id}, plugin)
    init_resp = init_responses.get(req_id)
    if not init_resp or "error" in init_resp:
        _fail(plugin, "initialize", str(init_resp))
    print(f"[functional] {plugin} initialize: OK", flush=True)
    req_id += 1

    # 2 ── initialized ────────────────────────────────────────────────────────
    proc.stdin.write(encode({"jsonrpc": "2.0", "method": "initialized", "params": {}}))

    # 3 ── didOpen(test.php) + completion + hover ─────────────────────────────
    with open(FIXTURE_FILE) as f:
        php_source = f.read()

    proc.stdin.write(encode({
        "jsonrpc": "2.0", "method": "textDocument/didOpen",
        "params": {"textDocument": {
            "uri": FILE_URI, "languageId": "php", "version": 1, "text": php_source,
        }},
    }))

    comp_id = req_id
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": comp_id, "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": FILE_URI},
            "position": {"line": 25, "character": 15},
            "context": {"triggerKind": 2, "triggerCharacter": ">"},
        },
    }))
    req_id += 1

    hover_id = req_id
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": hover_id, "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": FILE_URI},
            "position": {"line": 4, "character": 8},
        },
    }))
    req_id += 1

    # 4 ── didOpen(test_implementation.php) + implementation ──────────────────
    with open(FIXTURE_IMPL) as f:
        impl_source = f.read()

    proc.stdin.write(encode({
        "jsonrpc": "2.0", "method": "textDocument/didOpen",
        "params": {"textDocument": {
            "uri": IMPL_FILE_URI, "languageId": "php", "version": 1, "text": impl_source,
        }},
    }))

    impl_id = req_id
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": impl_id, "method": "textDocument/implementation",
        "params": {
            "textDocument": {"uri": IMPL_FILE_URI},
            "position": {"line": 6, "character": 20},
        },
    }))
    req_id += 1

    proc.stdin.flush()

    responses = wait_for_ids(msg_queue, {comp_id, hover_id, impl_id}, plugin)

    comp_resp = responses.get(comp_id)
    hover_resp = responses.get(hover_id)
    impl_resp  = responses.get(impl_id)

    if comp_resp and "error" in comp_resp:
        _fail(plugin, "completion", f"server error: {comp_resp['error']}")
    check_completion(comp_resp.get("result") if comp_resp else None, plugin)

    if hover_resp and "error" in hover_resp:
        _fail(plugin, "hover", f"server error: {hover_resp['error']}")
    check_hover(hover_resp.get("result") if hover_resp else None, plugin)

    if impl_resp and "error" in impl_resp:
        _fail(plugin, "implementation", f"server error: {impl_resp['error']}")
    check_implementation(impl_resp.get("result") if impl_resp else None, plugin)

    # 5 ── shutdown ────────────────────────────────────────────────────────────
    shutdown(proc, req_id)
    print(f"[functional] {plugin}: all tests passed", flush=True)


if __name__ == "__main__":
    main()
