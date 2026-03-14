# PHP LSP Docker — Claude Code

[![CI](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/ci.yml/badge.svg)](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/ci.yml)
[![Docker](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/docker-publish.yml)

Run **Intelephense** (free tier) and **[PHPantom](https://github.com/AJenbo/phpantom_lsp)** as Claude Code LSP servers via Docker — no local PHP toolchain required.

Three plugins to choose from:

| Feature                | Intelephense (free) |              PHPantom |                          Combined |
|------------------------|---------------------|----------------------:|----------------------------------:|
| Completion             | ✅                   |                     ✅ |                         ✅ merged |
| Go-to-definition       | ✅                   |                     ✅ |                         ✅ merged |
| Hover                  | ✅                   |            🚧 partial |                                ✅ |
| Find references        | ✅                   |             ❌ roadmap |                                ✅ |
| Diagnostics            | ✅                   |             ❌ roadmap |                                ✅ |
| Auto-import            | ❌ paid              |                     ✅ |                                ✅ |
| Laravel Eloquent       | ❌                   |                     ✅ |                                ✅ |
| Startup time           | ~5 s                |             **10 ms** |                             ~5 s |
| RAM usage              | ~520 MB             |              **7 MB** |                          ~527 MB |
| First-run image fetch  | ~30 s pull / build  |           ~30 s pull  |                      ~30 s pull |

> **Which should I use?**
>
> - **Combined** (`php-combined-docker`) — recommended. Runs both servers; PHPantom answers requests immediately (it's faster), Intelephense fills in diagnostics in the background.
> - **PHPantom** (`phpantom-docker`) — ultra-low RAM and near-instant startup. Best for large codebases and Laravel projects.
> - **Intelephense** (`intelephense-docker`) — reliable diagnostics and find-references on its own.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux) — **running**
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) **v2.1.50+**

> **If LSP features don't activate after installing the plugin**, add the following to your Claude Code `settings.json`:
>
> ```json
> "ENABLE_LSP_TOOL": "1"
> ```
>
> Open `settings.json` via **Claude Code → Settings → Edit settings.json** (or `~/.claude/settings.json`).

---

## Installation

### 1. Clone this repository

```bash
git clone https://github.com/tony-stark-eth/php-lsp-docker-claude-code.git
cd php-lsp-docker-claude-code
```

### 2. Run the setup script (optional)

```bash
bash setup.sh
```

Makes wrapper scripts executable and optionally pre-builds the Docker images. You can skip this — images build automatically on first Claude Code use.

### 3. Register the marketplace in Claude Code

```text
/plugin marketplace add tony-stark-eth/php-lsp-docker-claude-code
```

### 4. Install a plugin

```text
/plugins
```

1. Tab to **Marketplaces**
2. Enter `php-lsp-docker-claude-code` → **Browse plugins**
3. Select one plugin with `Space`:
   - `php-combined-docker` — both servers, merged results (recommended)
   - `intelephense-docker` — Intelephense only
   - `phpantom-docker` — PHPantom only
4. Press `i` to install
5. Restart Claude Code

---

## How it works

### Single-server plugins (intelephense-docker / phpantom-docker)

Each plugin ships a `bin/lsp-server.sh` wrapper that Claude Code treats as the LSP binary. On first use the wrapper pulls the pre-built image from GHCR (no compilation required), then proxies stdio directly to the container:

```text
Claude Code  ←──stdio──→  bin/lsp-server.sh  ←──docker run -i──→  LSP in container
```

If GHCR is unreachable the wrapper falls back to building the image locally.

### Combined plugin (php-combined-docker)

The combined plugin runs a Python multiplexer (`bin/lsp-multiplexer.py`) that fans every JSON-RPC request out to both servers simultaneously:

```text
                               ┌──docker run -i──→  Intelephense
Claude Code  ←──stdio──→  lsp-multiplexer.py
                               └──docker run -i──→  PHPantom
```

**Merge strategy** — PHPantom wins by default (it's faster):

| Method | Strategy |
|---|---|
| `initialize` | Wait for both; union of `ServerCapabilities` |
| `textDocument/completion` | PHPantom items first, then Intelephense items |
| `textDocument/definition` / `references` | PHPantom locations first, then Intelephense |
| `textDocument/hover` | PHPantom (fall back to Intelephense if null) |
| `textDocument/signatureHelp` | PHPantom (fall back if no signatures) |
| `textDocument/publishDiagnostics` | Merged per-URI from both servers |
| Everything else | PHPantom wins immediately; Intelephense response discarded |

The workspace is mounted **read-only** in all containers.

---

## Hooks

All three plugins ship `hooks/hooks.json` with automatic quality gates:

| Hook | Trigger | Action |
|---|---|---|
| `php-syntax-check` | PostToolUse (Write/Edit) | `php -l` on edited file (no-op if `php` not on PATH) |
| `php-cs-fixer` | PostToolUse (Write/Edit) | `vendor/bin/php-cs-fixer fix` (no-op if not installed) |
| `php-pre-commit-gate` | PreToolUse (git commit) | `phpstan` + `phpunit` blocking gate (no-op if not installed) |

All hooks are silent no-ops when the tools are not present, so they work out of the box with no configuration.

---

## Docker images

Pre-built images are published to the GitHub Container Registry and refreshed every Monday plus on every push to `main`:

| Image | GHCR path |
|---|---|
| Intelephense | `ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/intelephense:latest` |
| PHPantom | `ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest` |

Tags available: `latest`, `YYYY-MM-DD`, and short git SHA.

The wrapper scripts pull from GHCR automatically on first use. To force a refresh to the latest published image:

```bash
docker pull ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/intelephense:latest
docker pull ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest
```

---

## Updating

### Intelephense

Pull the latest published image:

```bash
docker pull ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/intelephense:latest
docker tag  ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/intelephense:latest claude-code-lsp-intelephense
```

Or rebuild locally from source:

```bash
docker build --no-cache -t claude-code-lsp-intelephense ./intelephense
```

### PHPantom

Pull the latest published image (no Rust compilation):

```bash
docker pull ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest
docker tag  ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest claude-code-lsp-phpantom
```

Or rebuild locally from the `main` branch:

```bash
docker build --no-cache -t claude-code-lsp-phpantom ./phpantom
```

Pin a specific PHPantom release with the `PHPANTOM_REF` build arg:

```bash
docker build --no-cache --build-arg PHPANTOM_REF=0.4.0 -t claude-code-lsp-phpantom ./phpantom
```

---

## Troubleshooting

### "Executable not found in $PATH"

The wrapper scripts must be executable. Run:

```bash
chmod +x intelephense/bin/lsp-server.sh phpantom/bin/lsp-server.sh combined/bin/lsp-server.sh
```

### "No LSP server available for file type: .php"

- Restart Claude Code after installing the plugin.
- Check the `/plugin` Errors tab inside Claude Code.
- On older Claude Code versions (&lt;v2.1.50) you may need `npx tweakcc --apply` to enable LSP plugin support.

### PHPantom build fails

PHPantom clones and compiles from source at build time and requires a network-connected Docker daemon. Check your Docker network settings. Alternatively, build manually:

```bash
cd phpantom && docker build -t claude-code-lsp-phpantom .
```

### Intelephense cross-file completions not working

Intelephense needs the project's Composer autoloader. Run `composer install` in your project root so the LSP can resolve all classes.

---

## Project structure

```text
php-lsp-docker-claude-code/
├── .claude-plugin/
│   └── marketplace.json          # Claude Code marketplace definition
├── .github/
│   ├── scripts/
│   │   ├── fixtures/test.php     # PHP fixture for functional CI tests
│   │   ├── lsp_smoke_test.py     # initialize smoke test (all 3 plugins)
│   │   └── lsp_functional_test.py# completion + hover functional tests
│   ├── workflows/ci.yml           # Validate → build → smoke → functional
│   └── workflows/docker-publish.yml # Build & push images to GHCR
├── intelephense/
│   ├── .lsp.json                 # Claude Code LSP plugin config
│   ├── plugin.json               # Plugin manifest
│   ├── Dockerfile                # node:22-slim + intelephense npm package
│   ├── hooks/hooks.json          # PostToolUse + PreToolUse PHP hooks
│   └── bin/lsp-server.sh         # Wrapper (auto-builds + docker run)
├── phpantom/
│   ├── .lsp.json                 # Claude Code LSP plugin config
│   ├── plugin.json               # Plugin manifest
│   ├── Dockerfile                # Rust builder + slim runtime
│   ├── hooks/hooks.json          # PostToolUse + PreToolUse PHP hooks
│   └── bin/lsp-server.sh         # Wrapper (auto-builds + docker run)
├── combined/
│   ├── .lsp.json                 # Claude Code LSP plugin config
│   ├── plugin.json               # Plugin manifest
│   ├── intelephense/Dockerfile   # Intelephense image (self-contained copy)
│   ├── phpantom/Dockerfile       # PHPantom image (self-contained copy)
│   ├── hooks/hooks.json          # PostToolUse + PreToolUse PHP hooks
│   └── bin/
│       ├── lsp-server.sh         # Entry point (exec lsp-multiplexer.py)
│       └── lsp-multiplexer.py    # Python LSP fan-out + merge engine
├── setup.sh                      # One-time setup helper
└── README.md
```

---

## Credits

- [Intelephense](https://intelephense.com/) by Ben Mewburn — MIT licensed npm package (free tier)
- [PHPantom](https://github.com/AJenbo/phpantom_lsp) by AJenbo — MIT licensed, ultra-fast Rust PHP LSP
- [zircote/lsp-tools](https://github.com/zircote/lsp-tools) and [zircote/lsp-marketplace](https://github.com/zircote/lsp-marketplace) by zircote — inspiration for plugin structure, hooks patterns, and marketplace schema
- [claude-code-lsps](https://github.com/Piebald-AI/claude-code-lsps) by Piebald-AI — LSP plugin system reference

## License

Personal Use / Non-Commercial — see [LICENSE](LICENSE) for full terms.
Commercial use requires written permission from the copyright holder.
