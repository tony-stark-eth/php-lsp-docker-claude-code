#!/usr/bin/env bash
# php-lsp-docker: Intelephense LSP wrapper for Claude Code
# Builds the Docker image on first run, then proxies stdio to the container.
set -euo pipefail

IMAGE_NAME="claude-code-lsp-intelephense"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="$(dirname "$SCRIPT_DIR")"

# ── Build image if it doesn't exist yet ────────────────────────────────────────
if ! docker image inspect "$IMAGE_NAME" > /dev/null 2>&1; then
  echo "[php-lsp-docker] Building Intelephense Docker image (first run)…" >&2
  docker build \
    --tag "$IMAGE_NAME" \
    --file "$DOCKERFILE_DIR/Dockerfile" \
    "$DOCKERFILE_DIR" >&2
  echo "[php-lsp-docker] Build complete." >&2
fi

# ── Run the LSP server ─────────────────────────────────────────────────────────
# Mount the project workspace at /workspace and pass stdio straight through.
# --user flag maps host UID/GID so file permissions work correctly.
exec docker run \
  --rm \
  --interactive \
  --user "$(id -u):$(id -g)" \
  --volume "${PWD}:/workspace:ro" \
  --workdir "/workspace" \
  "$IMAGE_NAME"
