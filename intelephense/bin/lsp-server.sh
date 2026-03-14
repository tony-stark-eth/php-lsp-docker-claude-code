#!/usr/bin/env bash
# php-lsp-docker: Intelephense LSP wrapper for Claude Code
# Builds the Docker image on first run, then proxies stdio to the container.
set -euo pipefail

IMAGE_NAME="claude-code-lsp-intelephense"
GHCR_IMAGE="ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/intelephense:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="$(dirname "$SCRIPT_DIR")"

# ── Ensure image is available (pull from GHCR, fall back to local build) ──────
if ! docker image inspect "$IMAGE_NAME" > /dev/null 2>&1; then
  echo "[php-lsp-docker] Pulling Intelephense from GHCR…" >&2
  if docker pull "$GHCR_IMAGE" > /dev/null 2>&1; then
    docker tag "$GHCR_IMAGE" "$IMAGE_NAME"
    echo "[php-lsp-docker] Pull complete." >&2
  else
    echo "[php-lsp-docker] Pull failed — building locally (first run, ~30s)…" >&2
    docker build \
      --tag "$IMAGE_NAME" \
      --file "$DOCKERFILE_DIR/Dockerfile" \
      "$DOCKERFILE_DIR" >&2
    echo "[php-lsp-docker] Build complete." >&2
  fi
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
