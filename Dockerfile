# syntax = docker/dockerfile:latest

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS base

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/backend"
LABEL authors="ahmed.elghareeb@proton.com"

# Pull in latest security patches before anything else
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Create non-root user early for improved security
RUN groupadd -r archetype && useradd -r -g archetype archetype

WORKDIR /deps

COPY pyproject.toml uv.lock ./
RUN uv sync --locked

ENV PATH="/deps/.venv/bin:$PATH"

FROM base AS final

# Ships the LOG_IN_FILE target inside the image, so file logging needs no
# per-environment provisioning; a volume mounted here inherits this ownership.
RUN mkdir -p /var/log/app && chown archetype:archetype /var/log/app

USER archetype
WORKDIR /app

COPY --chown=archetype:archetype . .

EXPOSE 80

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "80"]
