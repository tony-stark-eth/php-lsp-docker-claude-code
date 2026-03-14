# PHP LSP Docker — Claude Code

[![CI](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/ci.yml/badge.svg)](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/ci.yml)
[![Docker](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/tony-stark-eth/php-lsp-docker-claude-code/actions/workflows/docker-publish.yml)

Run **[PHPantom](https://github.com/AJenbo/phpantom_lsp)** as a Claude Code LSP server via Docker — no local PHP toolchain required.

| Feature                | PHPantom |
|------------------------|----------:|
| Completion             |        ✅ |
| Go-to-definition       |        ✅ |
| Hover                  |        ✅ |
| Find references        |        ✅ |
| Diagnostics            |        ✅ |
| Auto-import            |        ✅ |
| Rename                 |        ✅ |
| Go-to-implementation   |        ✅ |
| Workspace symbols      | 🚧 partial |
| Laravel Eloquent       |        ✅ |
| Generics / @template   |        ✅ |
| Startup time           | **< 1 s** |
| RAM usage              | **~21 MB** |
| First-run image fetch  | ~30 s pull |

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

### 4. Install the plugin

```text
/plugins
```

1. Tab to **Marketplaces**
2. Enter `php-lsp-docker-claude-code` → **Browse plugins**
3. Select `phpantom-docker` with `Space`
4. Press `i` to install
5. Restart Claude Code

---

## How it works

The plugin ships a `bin/lsp-server.sh` wrapper that Claude Code treats as the LSP binary. On first use the wrapper pulls the pre-built image from GHCR (no compilation required), then proxies stdio directly to the container:

```text
Claude Code  ←──stdio──→  bin/lsp-server.sh  ←──docker run -i──→  PHPantom
```

If GHCR is unreachable the wrapper falls back to building the image locally.

The workspace is mounted **read-only** inside the container.

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

The pre-built PHPantom image is published to the GitHub Container Registry and refreshed every Monday plus on every push to `main`:

| Image | GHCR path |
|---|---|
| PHPantom | `ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest` |

Tags available: `latest`, `YYYY-MM-DD`, and short git SHA.

The wrapper script pulls from GHCR automatically on first use. To force a refresh:

```bash
docker pull ghcr.io/tony-stark-eth/php-lsp-docker-claude-code/phpantom:latest
```

---

## Updating

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

The wrapper script must be executable. Run:

```bash
chmod +x phpantom/bin/lsp-server.sh
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

---

## Project structure

```text
php-lsp-docker-claude-code/
├── .claude-plugin/
│   └── marketplace.json          # Claude Code marketplace definition
├── .github/
│   ├── scripts/
│   │   ├── fixtures/test.php     # PHP fixture for functional CI tests
│   │   ├── lsp_smoke_test.py     # initialize smoke test
│   │   └── lsp_functional_test.py# completion + hover + implementation tests
│   ├── workflows/ci.yml           # Validate → build → smoke → functional
│   └── workflows/docker-publish.yml # Build & push PHPantom image to GHCR
├── phpantom/
│   ├── .lsp.json                 # Claude Code LSP plugin config
│   ├── plugin.json               # Plugin manifest
│   ├── Dockerfile                # Rust builder + slim runtime
│   ├── hooks/hooks.json          # PostToolUse + PreToolUse PHP hooks
│   └── bin/lsp-server.sh         # Wrapper (auto-pulls + docker run)
├── setup.sh                      # One-time setup helper
└── README.md
```

---

## Credits

- [PHPantom](https://github.com/AJenbo/phpantom_lsp) by AJenbo — MIT licensed, ultra-fast Rust PHP LSP
- [zircote/lsp-tools](https://github.com/zircote/lsp-tools) and [zircote/lsp-marketplace](https://github.com/zircote/lsp-marketplace) by zircote — inspiration for plugin structure, hooks patterns, and marketplace schema
- [claude-code-lsps](https://github.com/Piebald-AI/claude-code-lsps) by Piebald-AI — LSP plugin system reference

## Changelog

### 2026-03-14 — Dropped Intelephense from combined plugin; PHPantom only

After extended debugging, Intelephense was found to call `process.exit(1)` unconditionally after every workspace index completes — a bug reproducible across versions 1.10.4 through 1.17.3-beta. The crash fires even when the workspace is excluded (`files.exclude: ["**"]`) because Intelephense also indexes its built-in PHP stubs, and the exit handler fires when that internal scan finishes regardless of workspace content or configuration.

The `php-combined-docker` multiplexer was removed. PHPantom (`phpantom-docker`) is now the recommended and only active plugin. It covers all use cases previously provided by the combined setup: completion, go-to-definition, hover, diagnostics, rename, auto-import, and Laravel/Eloquent support — with lower RAM usage and near-instant startup.

---

## License

Personal Use / Non-Commercial — see [LICENSE](LICENSE) for full terms.
Commercial use requires written permission from the copyright holder.
