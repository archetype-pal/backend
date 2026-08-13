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
USER archetype
WORKDIR /app

COPY --chown=archetype:archetype . .

EXPOSE 80

# --proxy-headers makes uvicorn trust X-Forwarded-For/-Proto from the peer
# that connected to it and rewrite the ASGI scope's client/scheme
# accordingly — without it, every request's "client" is whichever proxy
# dialed this container (see compose.yaml: this service publishes no host
# port, so that's always Traefik), which is what made every visitor share
# one address in the access log (and, via REST_FRAMEWORK's NUM_PROXIES,
# would otherwise make DRF's per-IP throttles share one budget across the
# whole site too). --forwarded-allow-ips='*' is safe here specifically
# because nothing but Traefik/other containers on this compose project's
# networks can reach this container at all.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips=*"]
