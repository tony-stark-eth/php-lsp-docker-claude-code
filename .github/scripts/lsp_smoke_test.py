#!/usr/bin/env python3
"""
LSP smoke test — starts the PHPantom server, sends an initialize request,
and verifies the response contains ServerCapabilities.

Usage:
  python3 lsp_smoke_test.py phpantom
"""

import json
import os
import subprocess
import sys
import time
import threading

ENCODING = "utf-8"
TIMEOUT = 60  # seconds to wait for initialize response

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "processId": os.getpid(),
        "rootUri": "file:///workspace",
        "capabilities": {
            "textDocument": {
                "completion": {"completionItem": {"snippetSupport": True}},
                "hover": {},
                "definition": {},
                "references": {},
                "publishDiagnostics": {},
            }
        },
        "trace": "off",
    },
}

SHUTDOWN_REQUEST = {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}
EXIT_NOTIFICATION = {"jsonrpc": "2.0", "method": "exit"}


def encode(msg):
    body = json.dumps(msg, separators=(",", ":")).encode(ENCODING)
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


def start_server(plugin):
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    workspace = repo_root

    if plugin == "phpantom":
        return subprocess.Popen(
            [
                "docker", "run", "--rm", "--interactive",
                "--user", uid_gid,
                "--volume", f"{workspace}:/workspace:ro",
                "--workdir", "/workspace",
                "claude-code-lsp-phpantom",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    raise ValueError(f"Unknown plugin: {plugin}")


def drain_stderr(proc, label):
    """Print server stderr to our stderr in a background thread."""
    def _drain():
        for line in proc.stderr:
            sys.stderr.buffer.write(f"[{label}] ".encode() + line)
            sys.stderr.buffer.flush()
    t = threading.Thread(target=_drain, daemon=True)
    t.start()


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "phpantom":
        print("Usage: lsp_smoke_test.py phpantom", file=sys.stderr)
        sys.exit(1)

    plugin = sys.argv[1]
    print(f"[smoke] Starting {plugin}…", flush=True)

    proc = start_server(plugin)
    drain_stderr(proc, plugin)

    # Send initialize
    proc.stdin.write(encode(INITIALIZE_REQUEST))
    proc.stdin.flush()

    # Read messages until we find the response to id=1
    response = None
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        proc.stdout._mode = "rb" if hasattr(proc.stdout, "_mode") else None  # no-op
        msg = read_message(proc.stdout)
        if msg is None:
            print(f"[smoke] {plugin}: server closed stdout before responding", file=sys.stderr)
            sys.exit(1)
        if msg.get("id") == 1:
            response = msg
            break
        # Skip notifications (e.g. window/logMessage during startup)

    if response is None:
        print(f"[smoke] {plugin}: no initialize response within {TIMEOUT}s", file=sys.stderr)
        proc.kill()
        sys.exit(1)

    if "error" in response:
        print(f"[smoke] {plugin}: initialize returned error: {response['error']}", file=sys.stderr)
        proc.kill()
        sys.exit(1)

    result = response.get("result", {})
    capabilities = result.get("capabilities")
    if not isinstance(capabilities, dict):
        print(
            f"[smoke] {plugin}: initialize result missing 'capabilities': {result}",
            file=sys.stderr,
        )
        proc.kill()
        sys.exit(1)

    print(f"[smoke] {plugin}: OK — capabilities keys: {sorted(capabilities.keys())}", flush=True)

    # Graceful shutdown
    try:
        proc.stdin.write(encode(SHUTDOWN_REQUEST))
        proc.stdin.write(encode(EXIT_NOTIFICATION))
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


if __name__ == "__main__":
    main()
