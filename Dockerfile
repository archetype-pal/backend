# syntax = docker/dockerfile:latest

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS python

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/archetype3"
LABEL authors="ahmed.elghareeb@proton.com"

FROM python AS deps_builder

# Create celery user and group first
RUN groupadd -r celery && useradd -r -g celery celery

WORKDIR /deps

COPY pyproject.toml ./
COPY uv.lock ./

RUN uv sync --locked

ENV PATH="/deps/.venv/bin:$PATH"

WORKDIR /app

COPY . ./

# Set proper permissions
RUN chown -R celery:celery /app /deps

EXPOSE 80

# Switch to non-root user for better security
USER celery

CMD ["gunicorn", "config.wsgi:application" , "--bind", "0.0.0.0:80", "--workers", "4"]
