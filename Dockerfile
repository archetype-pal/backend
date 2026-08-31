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

# LOG_IN_FILE target, so enabling it needs no per-environment provisioning.
RUN mkdir -p /var/log/app && chown archetype:archetype /var/log/app

# Drop the base image's pip. Dependencies are resolved by `uv sync` into
# /deps/.venv, which is what the CMD below runs from, so pip is never invoked at
# runtime — but its *vendored* copies of msgpack and setuptools are exactly what
# the CD image scan flags (GHSA-6v7p-g79w-8964, CVE-2025-47273). Removing the
# code beats suppressing the finding, and a future real CVE in those packages
# still gets reported. Absolute path: PATH puts the venv's python first, and it
# is not the interpreter carrying pip.
RUN /usr/local/bin/python -c "\
import pathlib, shutil, sysconfig; \
site = pathlib.Path(sysconfig.get_paths()['purelib']); \
[shutil.rmtree(d, ignore_errors=True) for d in [*site.glob('pip'), *site.glob('pip-*.dist-info')]]" \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.*

USER archetype
WORKDIR /app

COPY --chown=archetype:archetype . .

EXPOSE 80

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "80"]
