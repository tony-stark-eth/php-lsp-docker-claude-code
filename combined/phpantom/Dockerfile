# ── Stage 1: Build phpantom_lsp from source ───────────────────────────────────
FROM rust:slim AS builder

# Install build dependencies (needed for the mago PHP parser and build scripts)
RUN apt-get update && apt-get install -y \
    git \
    pkg-config \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone the latest release of phpantom_lsp
ARG PHPANTOM_REF=main
RUN git clone --depth 1 --branch "$PHPANTOM_REF" \
    https://github.com/AJenbo/phpantom_lsp.git /src

WORKDIR /src

# Fetch dependencies as a separate layer so they are cached independently
# of source changes — only re-runs when Cargo.toml/Cargo.lock change.
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo fetch

# Build the binary (re-runs only when source or deps change)
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/target \
    cargo build --release && \
    cp /src/target/release/phpantom_lsp /phpantom_lsp

# ── Stage 2: Minimal runtime image ────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /phpantom_lsp /usr/local/bin/phpantom_lsp

RUN useradd -m -u 1001 lsp
USER lsp

WORKDIR /workspace

# phpantom_lsp communicates over stdio
ENTRYPOINT ["phpantom_lsp"]
