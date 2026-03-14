# PHP LSP Docker — Claude Code

Run **Intelephense** (free tier) and **[PHPantom](https://github.com/AJenbo/phpantom_lsp)** as Claude Code LSP servers via Docker — no local PHP toolchain required.

| Feature                | Intelephense (free) |              PHPantom |              Combined |
|------------------------|---------------------|----------------------:|----------------------:|
| Completion             | ✅                   |                     ✅ |              ✅ merged |
| Go-to-definition       | ✅                   |                     ✅ |              ✅ merged |
| Hover                  | ✅                   |            🚧 partial |                     ✅ |
| Find references        | ✅                   |             ❌ roadmap |                     ✅ |
| Diagnostics            | ✅                   |             ❌ roadmap |                     ✅ |
| Auto-import            | ❌ paid              |                     ✅ |                     ✅ |
| Laravel Eloquent       | ❌                   |                     ✅ |                     ✅ |
| Startup time           | ~5 s                |             **10 ms** |                  ~5 s |
| RAM usage              | ~520 MB             |              **7 MB** |               ~527 MB |
| Build time (first run) | ~30 s               | ~2 min (Rust compile) | ~2 min (in parallel)  |

> **Which should I use?**
>
> - **Combined** (`php-combined-docker`) — best results; runs both servers and merges responses via a Python multiplexer. Recommended if you don't mind the extra RAM.
> - **PHPantom** — ultra-low RAM and instant startup; great for large codebases and Laravel projects.
> - **Intelephense** — reliable diagnostics and find-references on its own.

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux) — **running**
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) **v2.1.50+**
- `npx tweakcc --apply` applied (required for LSP plugin loading — see [tweakcc](https://github.com/Piebald-AI/tweakcc))

---

## Installation

### 1. Clone this repository

```bash
git clone https://github.com/tony-stark-eth/php-lsp-docker-claude-code.git
cd php-lsp-docker-claude-code
```

### 2. Run the setup script

```bash
bash setup.sh
```

This makes the wrapper scripts executable and optionally pre-builds the Docker images.

### 3. Patch Claude Code (required once)

```bash
npx tweakcc --apply
```

### 4. Register the marketplace in Claude Code

```text
/plugin marketplace add tony-stark-eth/php-lsp-docker-claude-code
```

### 5. Install a plugin

```text
/plugins
```

1. Tab to **Marketplaces**
2. Enter `php-lsp-docker-claude-code` → **Browse plugins**
3. Select one of the three plugins with `Space`:
   - `php-combined-docker` — both servers, merged results (recommended)
   - `intelephense-docker` — Intelephense only
   - `phpantom-docker` — PHPantom only
4. Press `i` to install
5. Restart Claude Code

---

## How it works

Each plugin ships a small **wrapper shell script** (`bin/lsp-server.sh`) that Claude Code treats as the LSP binary. When Claude Code starts an LSP session:

1. The wrapper checks whether the Docker image exists; if not it builds it automatically.
2. It calls `docker run --rm -i` with the current working directory mounted as `/workspace`.
3. Stdio is piped directly — Claude Code and the LSP server talk over the same stdin/stdout channel as if the server were local.

```text
Claude Code  ←──stdio──→  bin/lsp-server.sh  ←──docker run -i──→  LSP in container
```

The workspace is mounted **read-only** so the containers cannot modify your files.

---

## Updating

### Intelephense

Rebuild to pick up the latest npm release:

```bash
docker build --no-cache -t claude-code-lsp-intelephense ./intelephense
```

### PHPantom

Rebuild to pick up the latest commits from the `main` branch:

```bash
docker build --no-cache -t claude-code-lsp-phpantom ./phpantom
```

Or pin a specific tag by changing the `PHPANTOM_REF` build arg:

```bash
docker build --no-cache --build-arg PHPANTOM_REF=0.4.0 -t claude-code-lsp-phpantom ./phpantom
```

---

## Troubleshooting

### "Executable not found in $PATH"

The wrapper scripts must be executable. Run:

```bash
chmod +x intelephense/bin/lsp-server.sh phpantom/bin/lsp-server.sh
```

### "No LSP server available for file type: .php"

- Make sure you ran `npx tweakcc --apply`.
- Restart Claude Code after installing the plugin.
- Check the `/plugin` Errors tab inside Claude Code.

### PHPantom build fails

PHPantom requires a network-connected Docker build to clone the source repo. Check your Docker network settings. Alternatively, build manually:

```bash
cd phpantom && docker build -t claude-code-lsp-phpantom .
```

### Intelephense cross-file completions not working

Intelephense needs the project's Composer autoloader. Run `composer install` in your project root so the LSP can find all classes.

---

## Project structure

```text
php-lsp-docker-claude-code/
├── .claude-plugin/
│   └── marketplace.json        # Claude Code marketplace definition
├── intelephense/
│   ├── .lsp.json               # Claude Code LSP plugin config
│   ├── plugin.json             # Plugin manifest
│   ├── Dockerfile              # node:22-slim + intelephense npm package
│   └── bin/
│       └── lsp-server.sh       # Wrapper script (auto-builds + docker run)
├── phpantom/
│   ├── .lsp.json               # Claude Code LSP plugin config
│   ├── plugin.json             # Plugin manifest
│   ├── Dockerfile              # Rust builder + slim runtime
│   └── bin/
│       └── lsp-server.sh       # Wrapper script (auto-builds + docker run)
├── setup.sh                    # One-time setup helper
└── README.md
```

---

## Credits

- [Intelephense](https://intelephense.com/) by Ben Mewburn — MIT licensed npm package (free tier)
- [PHPantom](https://github.com/AJenbo/phpantom_lsp) by AJenbo — MIT licensed, ultra-fast Rust PHP LSP
- [tweakcc](https://github.com/Piebald-AI/tweakcc) / [claude-code-lsps](https://github.com/Piebald-AI/claude-code-lsps) by Piebald-AI — LSP plugin system reference

## License

MIT
