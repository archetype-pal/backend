# syntax = docker/dockerfile:latest

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/backend"
LABEL authors="ahmed.elghareeb@proton.com"

# Create non-root user early for improved security
# RUN groupadd -r archetype && useradd -r -g archetype archetype

WORKDIR /deps

COPY pyproject.toml uv.lock ./
RUN uv sync --locked

ENV PATH="/deps/.venv/bin:$PATH"

FROM base AS final
# USER archetype
WORKDIR /app

COPY --chown=archetype:archetype . .

EXPOSE 80

CMD ["gunicorn", "config.wsgi:application" , "--bind", "0.0.0.0:80", "--workers", "4"]
