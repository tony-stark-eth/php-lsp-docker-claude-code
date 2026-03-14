#!/usr/bin/env python3
"""
PHP LSP multiplexer — fans out client requests to Intelephense + PHPantom
and merges their responses so Claude Code gets the best of both servers.

Merge strategy:
  initialize            merge ServerCapabilities (union of features)
  completion            concatenate item lists from both servers
  definition/references concatenate Location arrays
  hover                 prefer Intelephense (richer doc strings)
  signatureHelp         prefer whichever has signatures
  codeAction/docSymbol  concatenate lists
  diagnostics (notif)   merge per-URI whenever either server publishes
  everything else       prefer Intelephense, fall back to PHPantom
"""

import json
import os
import subprocess
import sys
import threading

ENCODING = "utf-8"


# ── LSP framing ──────────────────────────────────────────────────────────────

def read_message(stream):
    """Read one LSP message from a binary stream. Returns dict or None on EOF."""
    headers = {}
    while True:
        raw = stream.readline()
        if not raw:
            return None
        line = raw.decode(ENCODING).rstrip("\r\n")
        if not line:
            break
        key, _, value = line.partition(": ")
        headers[key] = value

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


def write_message(stream, msg):
    """Write one LSP message to a binary stream."""
    body = json.dumps(msg, separators=(",", ":")).encode(ENCODING)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING)
    stream.write(header + body)
    stream.flush()


# ── Merge helpers ─────────────────────────────────────────────────────────────

def _merge_capabilities(a, b):
    """Recursively merge two ServerCapabilities dicts (union of features)."""
    if not a:
        return b or {}
    if not b:
        return a
    result = dict(a)
    for k, v in b.items():
        if k not in result or result[k] is None:
            result[k] = v
        elif isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge_capabilities(result[k], v)
    return result


def _to_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def merge_results(method, r_phantom, r_intel):
    """
    Merge two LSP results. PHPantom takes precedence for all single-winner
    methods; Intelephense is the fallback (adds diagnostics and references).

    r_phantom = PHPantom result (server index 1)
    r_intel   = Intelephense result (server index 0)
    """
    if r_phantom is None:
        return r_intel
    if r_intel is None:
        return r_phantom

    if method == "initialize":
        # Start from PHPantom capabilities, fill gaps with Intelephense
        merged = dict(r_phantom)
        merged["capabilities"] = _merge_capabilities(
            r_phantom.get("capabilities", {}), r_intel.get("capabilities", {})
        )
        return merged

    if method == "textDocument/completion":
        def extract(r):
            if isinstance(r, dict):
                return r.get("items", [])
            return r if isinstance(r, list) else []

        # PHPantom items first (higher priority in UI ranking)
        items = extract(r_phantom) + extract(r_intel)
        incomplete = (isinstance(r_phantom, dict) and r_phantom.get("isIncomplete", False)) or \
                     (isinstance(r_intel, dict) and r_intel.get("isIncomplete", False))
        return {"isIncomplete": bool(incomplete), "items": items}

    if method in (
        "textDocument/definition",
        "textDocument/declaration",
        "textDocument/typeDefinition",
        "textDocument/implementation",
        "textDocument/references",
    ):
        # PHPantom locations first
        return _to_list(r_phantom) + _to_list(r_intel)

    if method in ("textDocument/codeAction", "textDocument/documentSymbol",
                  "workspace/symbol"):
        return _to_list(r_phantom) + _to_list(r_intel)

    if method == "textDocument/hover":
        # PHPantom preferred; fall back to Intelephense
        return r_phantom if r_phantom is not None else r_intel

    if method == "textDocument/signatureHelp":
        return r_phantom if (r_phantom and r_phantom.get("signatures")) else r_intel

    # Default: prefer PHPantom
    return r_phantom


# ── Multiplexer ───────────────────────────────────────────────────────────────

class Multiplexer:
    def __init__(self, proc_intel, proc_phantom):
        self._procs = [proc_intel, proc_phantom]
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._diag_lock = threading.Lock()
        # id -> {method, received, results, errors}
        self._pending = {}
        # uri -> [intel_diags, phantom_diags]
        self._diagnostics = {}

    def _write_to_client(self, msg):
        with self._write_lock:
            write_message(sys.stdout.buffer, msg)

    # Methods where we must wait for both servers before responding,
    # because merging both results is essential (e.g. capability negotiation).
    _WAIT_FOR_BOTH = frozenset({"initialize"})

    def _handle_server_message(self, msg, server_idx):
        """Called from per-server reader threads."""
        msg_id = msg.get("id")
        method = msg.get("method")

        # Server-to-client notification (no id, has method)
        if msg_id is None and method:
            if method == "textDocument/publishDiagnostics":
                self._merge_diagnostics(msg, server_idx)
            else:
                self._write_to_client(msg)
            return

        # Response to a client request (has id, no method key)
        if msg_id is not None and "method" not in msg:
            with self._pending_lock:
                if msg_id not in self._pending:
                    # Unexpected (e.g. server-initiated request) — pass through
                    self._write_to_client(msg)
                    return

                entry = self._pending[msg_id]

                if entry.get("resolved"):
                    return  # PHPantom already answered; discard Intelephense's late response

                entry["received"] += 1
                if "result" in msg:
                    entry["results"][server_idx] = msg["result"]
                elif "error" in msg:
                    entry["errors"][server_idx] = msg["error"]

                # PHPantom (idx=1) wins immediately when it has a non-null result,
                # unless this method requires both responses to merge correctly.
                phantom_result = entry["results"].get(1)
                both_responded = entry["received"] >= 2
                wait_for_both  = entry["method"] in self._WAIT_FOR_BOTH

                if (phantom_result is not None and not wait_for_both) or both_responded:
                    entry["resolved"] = True
                    del self._pending[msg_id]
                else:
                    return  # still waiting

            # Outside the lock — resolve and send to client.
            # server_idx 0 = Intelephense, 1 = PHPantom.
            if entry["results"]:
                r_phantom = entry["results"].get(1)
                r_intel   = entry["results"].get(0)
                merged = merge_results(entry["method"], r_phantom, r_intel)
                self._write_to_client({"jsonrpc": "2.0", "id": msg_id, "result": merged})
            else:
                self._write_to_client(
                    {"jsonrpc": "2.0", "id": msg_id, "error": next(iter(entry["errors"].values()))}
                )

    def _merge_diagnostics(self, msg, server_idx):
        params = msg.get("params", {})
        uri = params.get("uri", "")
        diags = params.get("diagnostics", [])

        with self._diag_lock:
            if uri not in self._diagnostics:
                self._diagnostics[uri] = [[], []]
            self._diagnostics[uri][server_idx] = diags
            combined = self._diagnostics[uri][0] + self._diagnostics[uri][1]

        self._write_to_client({
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {"uri": uri, "diagnostics": combined},
        })

    def _reader_thread(self, proc, server_idx):
        name = ["Intelephense", "PHPantom"][server_idx]
        try:
            while True:
                msg = read_message(proc.stdout)
                if msg is None:
                    break
                self._handle_server_message(msg, server_idx)
        except Exception as exc:
            print(f"[php-lsp-mux] {name} reader error: {exc}", file=sys.stderr, flush=True)

    def run(self):
        for i, proc in enumerate(self._procs):
            t = threading.Thread(target=self._reader_thread, args=(proc, i), daemon=True)
            t.start()

        stdin = sys.stdin.buffer
        while True:
            msg = read_message(stdin)
            if msg is None:
                break

            msg_id = msg.get("id")
            method = msg.get("method")

            # Track outgoing requests so we can pair responses
            if msg_id is not None and method:
                with self._pending_lock:
                    self._pending[msg_id] = {
                        "method": method,
                        "received": 0,
                        "results": {},   # keyed by server_idx: 0=Intelephense, 1=PHPantom
                        "errors": {},
                    }

            # Fan out to both servers
            for proc in self._procs:
                try:
                    write_message(proc.stdin, msg)
                except BrokenPipeError:
                    pass

        # Client disconnected — signal servers to shut down
        for proc in self._procs:
            try:
                proc.stdin.close()
            except Exception:
                pass


# ── Entry point ───────────────────────────────────────────────────────────────

def _build_image(name, dockerfile_dir):
    label = "Intelephense" if "intelephense" in name else "PHPantom"
    extra = " (compiles Rust, ~2 min)" if "phpantom" in name else ""
    print(f"[php-lsp-docker] Building {label}{extra}…", file=sys.stderr, flush=True)
    subprocess.run(
        [
            "docker", "build",
            "--tag", name,
            "--file", os.path.join(dockerfile_dir, "Dockerfile"),
            dockerfile_dir,
        ],
        check=True,
        stderr=sys.stderr,
    )
    print(f"[php-lsp-docker] {label} ready.", file=sys.stderr, flush=True)


def _ensure_images_parallel(images_and_dirs):
    """Build any missing images in parallel."""
    threads = []
    for name, dockerfile_dir in images_and_dirs:
        result = subprocess.run(
            ["docker", "image", "inspect", name], capture_output=True
        )
        if result.returncode != 0:
            t = threading.Thread(target=_build_image, args=(name, dockerfile_dir))
            t.start()
            threads.append(t)
    for t in threads:
        t.join()


def _start_server(image, workspace, uid_gid):
    return subprocess.Popen(
        [
            "docker", "run", "--rm", "--interactive",
            "--user", uid_gid,
            "--volume", f"{workspace}:/workspace:ro",
            "--workdir", "/workspace",
            image,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    _ensure_images_parallel([
        ("claude-code-lsp-intelephense", os.path.join(plugin_dir, "intelephense")),
        ("claude-code-lsp-phpantom",     os.path.join(plugin_dir, "phpantom")),
    ])

    workspace = os.getcwd()
    uid_gid = f"{os.getuid()}:{os.getgid()}"

    proc1 = _start_server("claude-code-lsp-intelephense", workspace, uid_gid)
    proc2 = _start_server("claude-code-lsp-phpantom",     workspace, uid_gid)

    Multiplexer(proc1, proc2).run()

    proc1.wait()
    proc2.wait()
