#!/usr/bin/env bash
# setup.sh — Pre-build Docker images and make wrapper scripts executable.
# Run this once after cloning the repository.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== PHP LSP Docker — Claude Code Setup ==="
echo ""

# ── Check prerequisites ────────────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
  echo "❌  Docker not found. Install Docker Desktop (https://www.docker.com/products/docker-desktop/) and try again."
  exit 1
fi

if ! docker info &> /dev/null; then
  echo "❌  Docker daemon is not running. Start Docker Desktop and try again."
  exit 1
fi

echo "✅  Docker is available."
echo ""

# ── Make wrapper scripts executable ───────────────────────────────────────────
chmod +x "$REPO_DIR/intelephense/bin/lsp-server.sh"
chmod +x "$REPO_DIR/phpantom/bin/lsp-server.sh"
echo "✅  Wrapper scripts made executable."
echo ""

# ── Ask which images to pre-build ─────────────────────────────────────────────
echo "Which images would you like to pre-build now?"
echo "  1) Intelephense only (fastest — node-based, ~200 MB)"
echo "  2) PHPantom only     (compiles Rust — ~2 min, ~100 MB final)"
echo "  3) Both"
echo "  4) Skip (build automatically on first Claude Code use)"
echo ""
read -rp "Choice [1-4]: " choice

case "$choice" in
  1)
    echo ""
    echo "Building Intelephense image…"
    docker build --tag "claude-code-lsp-intelephense" "$REPO_DIR/intelephense"
    echo "✅  Intelephense image built."
    ;;
  2)
    echo ""
    echo "Building PHPantom image (compiling Rust — this takes ~2 minutes)…"
    docker build --tag "claude-code-lsp-phpantom" "$REPO_DIR/phpantom"
    echo "✅  PHPantom image built."
    ;;
  3)
    echo ""
    echo "Building Intelephense image…"
    docker build --tag "claude-code-lsp-intelephense" "$REPO_DIR/intelephense"
    echo "✅  Intelephense image built."
    echo ""
    echo "Building PHPantom image (compiling Rust — this takes ~2 minutes)…"
    docker build --tag "claude-code-lsp-phpantom" "$REPO_DIR/phpantom"
    echo "✅  PHPantom image built."
    ;;
  *)
    echo "Skipping pre-build. Images will be built automatically on first use."
    ;;
esac

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next: register the Claude Code marketplace and install the plugins."
echo "See README.md for full instructions."
