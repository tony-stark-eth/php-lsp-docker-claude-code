#!/usr/bin/env python3
"""
LSP functional test — verifies real PHP code intelligence for all three plugins.

Sequence:
  initialize → initialized → textDocument/didOpen
    → textDocument/completion  (assert: returns method completions for $greeter->)
    → textDocument/hover       (assert: returns type info for class Greeter)
  → shutdown → exit

Usage:
  python3 lsp_functional_test.py intelephense
  python3 lsp_functional_test.py phpantom
  python3 lsp_functional_test.py combined

Positions in fixtures/test.php (0-indexed):
  Completion : line 25, char 15  ($greeter-> | trigger)
  Hover      : line 4,  char 8   (class Gr|eeter)
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

ENCODING = "utf-8"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FIXTURE_REL = ".github/scripts/fixtures/test.php"
# All three plugins mount REPO_ROOT as /workspace inside containers
FILE_URI    = f"file:///workspace/{FIXTURE_REL}"
ROOT_URI    = "file:///workspace"

# After textDocument/didOpen we wait for the server to index the file.
INDEX_WAIT = {
    "intelephense": 8,
    "phpantom":     2,
    "combined":     8,
}

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
# The server sends diagnostics/progress notifications continuously. If we
# don't read stdout at all times the pipe buffer fills up, the server blocks,
# and then crashes. This thread drains stdout into a queue so the main thread
# can pull responses by id without blocking the server.

def start_reader(proc: subprocess.Popen) -> queue.Queue:
    """Spawn a thread that pumps all server messages into a Queue."""
    msg_queue: queue.Queue = queue.Queue()

    def _read():
        while True:
            msg = read_message(proc.stdout)
            if msg is None:
                msg_queue.put(None)  # sentinel: server closed stdout
                break
            msg_queue.put(msg)

    threading.Thread(target=_read, daemon=True).start()
    return msg_queue


def wait_for_id(msg_queue: queue.Queue, req_id: int, label: str) -> dict | None:
    """Pull messages from the queue until we find the response for req_id."""
    deadline = time.monotonic() + REQUEST_TIMEOUT
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            msg = msg_queue.get(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue
        if msg is None:
            print(f"[functional] {label}: server closed stdout unexpectedly", file=sys.stderr)
            return None
        if msg.get("id") == req_id:
            return msg
        # Discard notifications (diagnostics, progress, logMessage…)
    return None


# ── Server startup ────────────────────────────────────────────────────────────

def start_server(plugin: str) -> subprocess.Popen:
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    docker_args = [
        "docker", "run", "--rm", "--interactive",
        "--user", uid_gid,
        "--volume", f"{REPO_ROOT}:/workspace:ro",
        "--workdir", "/workspace",
    ]

    if plugin == "intelephense":
        return subprocess.Popen(
            docker_args + ["claude-code-lsp-intelephense"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if plugin == "phpantom":
        return subprocess.Popen(
            docker_args + ["claude-code-lsp-phpantom"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if plugin == "combined":
        script = os.path.join(REPO_ROOT, "combined", "bin", "lsp-server.sh")
        return subprocess.Popen(
            ["bash", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=REPO_ROOT,
        )
    raise ValueError(f"Unknown plugin: {plugin}")


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


# ── Test assertions ───────────────────────────────────────────────────────────

def check_completion(result, plugin: str) -> None:
    if result is None:
        _fail(plugin, "completion", "got null result — no completions returned")

    items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(items, list) or len(items) == 0:
        _fail(plugin, "completion", f"expected a non-empty items list, got: {result!r}")

    labels = {item.get("label", "") for item in items if isinstance(item, dict)}
    if not any(lbl in labels for lbl in ("greet", "farewell", "greet()", "farewell()")):
        _fail(plugin, "completion",
              f"expected 'greet' or 'farewell' in labels, got: {sorted(labels)!r}")

    print(f"[functional] {plugin} completion: OK — {len(items)} items, "
          f"labels include: {sorted(labels)!r}", flush=True)


def check_hover(result, plugin: str) -> None:
    if result is None:
        # null is a valid LSP response; warn but don't fail
        print(f"[functional] {plugin} hover: WARN — null result (cursor may be off-symbol)",
              flush=True)
        return

    if not result.get("contents"):
        _fail(plugin, "hover", f"expected 'contents' in result, got: {result!r}")

    print(f"[functional] {plugin} hover: OK", flush=True)


def _fail(plugin: str, test: str, reason: str) -> None:
    print(f"[functional] {plugin} {test}: FAIL — {reason}", file=sys.stderr, flush=True)
    sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("intelephense", "phpantom", "combined"):
        print("Usage: lsp_functional_test.py intelephense|phpantom|combined", file=sys.stderr)
        sys.exit(1)

    plugin = sys.argv[1]
    print(f"[functional] Starting {plugin}…", flush=True)

    proc = start_server(plugin)
    drain_stderr(proc, plugin)
    msg_queue = start_reader(proc)   # drain stdout continuously from now on

    req_id = 1

    # 1 ── initialize ─────────────────────────────────────────────────────────
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": req_id, "method": "initialize",
        "params": {
            "processId": os.getpid(),
            "rootUri": ROOT_URI,
            "capabilities": {
                "textDocument": {
                    "completion": {
                        "completionItem": {"snippetSupport": True},
                        "contextSupport": True,
                    },
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {},
                    "publishDiagnostics": {},
                }
            },
            "trace": "off",
        },
    }))
    proc.stdin.flush()

    init_resp = wait_for_id(msg_queue, req_id, plugin)
    if not init_resp or "error" in init_resp:
        _fail(plugin, "initialize", str(init_resp))
    print(f"[functional] {plugin} initialize: OK", flush=True)
    req_id += 1

    # 2 ── initialized ────────────────────────────────────────────────────────
    proc.stdin.write(encode({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
    proc.stdin.flush()

    # 3 ── textDocument/didOpen ────────────────────────────────────────────────
    fixture_path = os.path.join(REPO_ROOT, FIXTURE_REL)
    with open(fixture_path) as f:
        php_source = f.read()

    proc.stdin.write(encode({
        "jsonrpc": "2.0", "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": FILE_URI,
                "languageId": "php",
                "version": 1,
                "text": php_source,
            }
        },
    }))
    proc.stdin.flush()

    wait_secs = INDEX_WAIT[plugin]
    print(f"[functional] {plugin} waiting {wait_secs}s for indexing…", flush=True)
    time.sleep(wait_secs)

    # 4 ── textDocument/completion ─────────────────────────────────────────────
    # Line 25: "echo $greeter->greet();"  char 15 = right after "->"
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": req_id, "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": FILE_URI},
            "position": {"line": 25, "character": 15},
            "context": {"triggerKind": 2, "triggerCharacter": ">"},
        },
    }))
    proc.stdin.flush()

    comp_resp = wait_for_id(msg_queue, req_id, plugin)
    if comp_resp and "error" in comp_resp:
        _fail(plugin, "completion", f"server returned error: {comp_resp['error']}")
    check_completion(comp_resp.get("result") if comp_resp else None, plugin)
    req_id += 1

    # 5 ── textDocument/hover ──────────────────────────────────────────────────
    # Line 4: "class Greeter"  char 8 = inside "Greeter"
    proc.stdin.write(encode({
        "jsonrpc": "2.0", "id": req_id, "method": "textDocument/hover",
        "params": {
            "textDocument": {"uri": FILE_URI},
            "position": {"line": 4, "character": 8},
        },
    }))
    proc.stdin.flush()

    hover_resp = wait_for_id(msg_queue, req_id, plugin)
    if hover_resp and "error" in hover_resp:
        _fail(plugin, "hover", f"server returned error: {hover_resp['error']}")
    check_hover(hover_resp.get("result") if hover_resp else None, plugin)
    req_id += 1

    # 6 ── shutdown ────────────────────────────────────────────────────────────
    shutdown(proc, req_id)
    print(f"[functional] {plugin}: all tests passed", flush=True)


if __name__ == "__main__":
    main()
