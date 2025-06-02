# syntax = docker/dockerfile:latest

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/archetype3"
LABEL authors="ahmed.elghareeb@proton.com"

FROM python AS deps_builder

WORKDIR /deps

COPY pyproject.toml ./
COPY uv.lock ./

RUN uv sync --locked

ENV PATH="/deps/.venv/bin:$PATH"

WORKDIR /app

COPY . ./

EXPOSE 80
CMD ["gunicorn", "config.wsgi:application" , "--bind", "0.0.0.0:80", "--workers", "4"]
