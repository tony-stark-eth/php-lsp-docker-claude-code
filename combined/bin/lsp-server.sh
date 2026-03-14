#!/usr/bin/env bash
# php-lsp-docker: combined LSP wrapper for Claude Code
# Builds both Docker images (in parallel on first run), then starts the
# Python multiplexer which fans out requests to Intelephense + PHPantom.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/lsp-multiplexer.py"
