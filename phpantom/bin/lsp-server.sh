#!/usr/bin/env bash
# php-lsp-docker: PHPantom LSP wrapper for Claude Code
# Builds the Docker image on first run, then proxies stdio to the container.
set -euo pipefail

IMAGE_NAME="claude-code-lsp-phpantom"
GHCR_IMAGE="ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="$(dirname "$SCRIPT_DIR")"

# ── Ensure image is available (pull from GHCR, fall back to local build) ──────
if ! docker image inspect "$IMAGE_NAME" > /dev/null 2>&1; then
  echo "[php-lsp-docker] Pulling PHPantom from GHCR…" >&2
  if docker pull "$GHCR_IMAGE" > /dev/null 2>&1; then
    docker tag "$GHCR_IMAGE" "$IMAGE_NAME"
    echo "[php-lsp-docker] Pull complete." >&2
  else
    echo "[php-lsp-docker] Pull failed — building locally (first run, compiles Rust ~2 min)…" >&2
    docker build \
      --tag "$IMAGE_NAME" \
      --file "$DOCKERFILE_DIR/Dockerfile" \
      "$DOCKERFILE_DIR" >&2
    echo "[php-lsp-docker] Build complete." >&2
  fi
fi

# ── Run the LSP server ─────────────────────────────────────────────────────────
exec docker run \
  --rm \
  --interactive \
  --user "$(id -u):$(id -g)" \
  --volume "${PWD}:/workspace:ro" \
  --workdir "/workspace" \
  "$IMAGE_NAME"
