# syntax = docker/dockerfile:latest

# The self-hosted glyph encoder (AI programme W1.2). See server.py.
FROM ghcr.io/astral-sh/uv:python3.15-trixie-slim

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/backend"

ARG APT_REFRESH=""
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

RUN groupadd -r embedder && useradd -r -g embedder embedder

WORKDIR /deps
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-cache
ENV PATH="/deps/.venv/bin:$PATH"

# The weights, fetched once at build time at a pinned revision (Apache-2.0),
# then the Hub is switched off: a vector always names the weights that made it.
ENV EMBEDDER_MODEL=facebook/dinov2-small \
    EMBEDDER_REVISION=ed25f3a31f01632728cabb09d1542f84ab7b0056 \
    HF_HOME=/models
RUN python -c "import os; from huggingface_hub import snapshot_download; \
snapshot_download(os.environ['EMBEDDER_MODEL'], revision=os.environ['EMBEDDER_REVISION'], \
allow_patterns=['config.json', 'model.safetensors'])"
ENV HF_HUB_OFFLINE=1

WORKDIR /app
COPY server.py ./

USER embedder
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
CMD ["python", "server.py"]
