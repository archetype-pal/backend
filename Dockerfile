# syntax = docker/dockerfile:latest

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS base

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/backend"
LABEL authors="ahmed.elghareeb@proton.com"

# Pull in latest security patches before anything else.
# libvips-tools provides the `vips` CLI used by the upload-ingest pipeline
# (apps.uploads) to convert uploads to lossless JP2 before SIPI serves them.
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends libvips-tools && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user early for improved security
RUN groupadd -r archetype && useradd -r -g archetype archetype

WORKDIR /deps

COPY pyproject.toml uv.lock ./
RUN uv sync --locked

ENV PATH="/deps/.venv/bin:$PATH"

FROM base AS final
USER archetype
WORKDIR /app

COPY --chown=archetype:archetype . .

EXPOSE 80

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "80"]
