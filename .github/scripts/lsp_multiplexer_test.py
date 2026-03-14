#!/usr/bin/env python3
"""
Multiplexer regression tests — verifies bug fixes in lsp-multiplexer.py.

Bug 1 (server-initiated requests):
  PHPantom sends window/workDoneProgress/create (has BOTH id AND method)
  right after initialized. The multiplexer must not drop it — it must
  auto-ack the server (so it unblocks) and forward as a notification to
  the client. Without the fix the server hangs on the missing ack and
  subsequent LSP requests stall.

Bug 2 (null result hang):
  When PHPantom responds with JSON null the multiplexer stores None in
  entry["results"][1]. The old check (phantom_result is not None) cannot
  distinguish "not responded yet" from "responded with null", so it keeps
  waiting for Intelephense indefinitely. The fix checks key presence
  (1 in entry["results"]) instead. The hover request below hits exactly
  this path: PHPantom returns null at line 4 char 8, Intelephense has the
  answer. Without the fix, the response would only arrive after Intelephense
  responds (slow on large projects). With the fix, PHPantom's null
  immediately resolves the request.

Usage:
  python3 lsp_multiplexer_test.py
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

ENCODING  = "utf-8"
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(os.path.dirname(SCRIPT_DIR))
FIXTURE_DIR = os.path.join(SCRIPT_DIR, "fixtures")


# ── LSP helpers (duplicated from functional test for standalone execution) ────

def encode(msg: dict) -> bytes:
    body   = json.dumps(msg, separators=(",", ":")).encode(ENCODING)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING)
    return header + body


def read_message(stream):
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


def start_combined(fixture_dir: str) -> tuple[subprocess.Popen, queue.Queue]:
    script = os.path.join(REPO_ROOT, "combined", "bin", "lsp-server.sh")
    proc = subprocess.Popen(
        ["bash", script],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=fixture_dir,
    )
    # drain stderr so it doesn't block
    threading.Thread(
        target=lambda: [None for _ in proc.stderr], daemon=True
    ).start()

    q: queue.Queue = queue.Queue()
    def _reader():
        while True:
            msg = read_message(proc.stdout)
            q.put(msg)
            if msg is None:
                break
    threading.Thread(target=_reader, daemon=True).start()
    return proc, q


def wait_for_id(q: queue.Queue, req_id: int, timeout: float = 30.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = q.get(timeout=min(1.0, deadline - time.monotonic()))
        except queue.Empty:
            continue
        if msg is None:
            return None
        if msg.get("id") == req_id:
            return msg
    return None


def collect(q: queue.Queue, duration: float) -> list[dict]:
    """Drain queue for duration seconds, return all messages collected."""
    msgs = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            msg = q.get(timeout=min(0.2, deadline - time.monotonic()))
            if msg is not None:
                msgs.append(msg)
        except queue.Empty:
            pass
    return msgs


def kill(proc: subprocess.Popen) -> None:
    try:
        proc.stdin.write(encode({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None}))
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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_bug1_server_initiated_request_is_not_dropped() -> None:
    """
    Bug 1: after initialized PHPantom sends window/workDoneProgress/create
    (has both id AND method). The multiplexer must forward it to the client
    as a notification (so the UI can show progress) AND auto-ack the server
    so it is not left waiting for a response that would never come.

    Without the fix the message is silently dropped and PHPantom stalls.
    With the fix the client receives a window/workDoneProgress/create
    notification within a few seconds of initialized.
    """
    print("test_bug1_server_initiated_request_is_not_dropped … ", end="", flush=True)
    proc, q = start_combined(FIXTURE_DIR)

    try:
        # initialize
        proc.stdin.write(encode({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"processId": os.getpid(), "rootUri": "file:///workspace",
                       "capabilities": {}, "trace": "off"},
        }))
        proc.stdin.flush()
        init_resp = wait_for_id(q, 1, timeout=15)
        assert init_resp and "error" not in init_resp, f"initialize failed: {init_resp}"

        # Send initialized + didOpen to trigger PHPantom's indexing start
        with open(os.path.join(FIXTURE_DIR, "test.php")) as f:
            src = f.read()
        proc.stdin.write(encode({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        proc.stdin.write(encode({
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": "file:///workspace/test.php",
                                        "languageId": "php", "version": 1, "text": src}},
        }))
        proc.stdin.flush()

        # Collect all messages for 4s — the workDoneProgress/create notification
        # should arrive forwarded from the multiplexer within that window.
        msgs = collect(q, duration=4.0)
        methods = [m.get("method") for m in msgs if "method" in m]

        assert "window/workDoneProgress/create" in methods, (
            f"Bug 1 still present: window/workDoneProgress/create was not forwarded "
            f"to the client. Got methods: {methods}"
        )
        print("OK")
    finally:
        kill(proc)


def test_bug2_phantom_null_resolves_immediately() -> None:
    """
    Bug 2: when PHPantom responds with JSON null the entry in _pending must
    be resolved immediately rather than waiting for Intelephense.

    We send textDocument/hover at a position where PHPantom returns null
    (line 4 char 8 in test.php). The response must arrive within 3 seconds
    even if Intelephense is slow — because PHPantom's null should be enough
    to close the request.

    Without the fix the hover request blocks until Intelephense responds
    (which can be many seconds on large projects, causing a perceived hang).
    """
    print("test_bug2_phantom_null_resolves_immediately … ", end="", flush=True)
    proc, q = start_combined(FIXTURE_DIR)

    try:
        proc.stdin.write(encode({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"processId": os.getpid(), "rootUri": "file:///workspace",
                       "capabilities": {"textDocument": {"hover": {}}}, "trace": "off"},
        }))
        proc.stdin.flush()
        init_resp = wait_for_id(q, 1, timeout=15)
        assert init_resp and "error" not in init_resp, f"initialize failed: {init_resp}"

        with open(os.path.join(FIXTURE_DIR, "test.php")) as f:
            src = f.read()
        proc.stdin.write(encode({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        proc.stdin.write(encode({
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": "file:///workspace/test.php",
                                        "languageId": "php", "version": 1, "text": src}},
        }))
        # Hover at line 4 char 8 — PHPantom returns null, Intelephense has a result.
        # With the bug: multiplexer waits for Intelephense (potentially forever).
        # With the fix: PHPantom's null resolves the request; if Intelephense already
        # responded it is merged in; otherwise null is returned immediately.
        proc.stdin.write(encode({
            "jsonrpc": "2.0", "id": 10, "method": "textDocument/hover",
            "params": {"textDocument": {"uri": "file:///workspace/test.php"},
                       "position": {"line": 4, "character": 8}},
        }))
        proc.stdin.flush()

        t0 = time.monotonic()
        resp = wait_for_id(q, 10, timeout=3.0)
        elapsed = time.monotonic() - t0

        assert resp is not None, (
            f"Bug 2 still present: hover request timed out after 3s "
            f"(PHPantom's null result did not resolve the request)"
        )
        # Elapsed should be well under 3s; with the fix it's typically <1s
        print(f"OK — response in {elapsed:.2f}s, result={resp.get('result') is not None and 'non-null' or 'null'}")
    finally:
        kill(proc)


def main() -> None:
    failures = []
    for test in [test_bug1_server_initiated_request_is_not_dropped,
                 test_bug2_phantom_null_resolves_immediately]:
        try:
            test()
        except AssertionError as exc:
            print(f"FAIL — {exc}")
            failures.append(test.__name__)
        except Exception as exc:
            print(f"ERROR — {exc}")
            failures.append(test.__name__)

    if failures:
        print(f"\n{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    else:
        print("\nAll multiplexer regression tests passed.")


if __name__ == "__main__":
    main()
