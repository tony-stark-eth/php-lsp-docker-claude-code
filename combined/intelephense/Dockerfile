FROM node:22-slim

# Install intelephense (free version via npm - no license key required for core features)
RUN npm install -g intelephense@latest

# Set a non-root user for safety
RUN useradd -m -u 1001 lsp
USER lsp

WORKDIR /workspace

# intelephense communicates over stdio by default
ENTRYPOINT ["intelephense", "--stdio"]
