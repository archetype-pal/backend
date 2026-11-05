# syntax = docker/dockerfile:latest

# Self-hosted handwritten text recognition (AI programme W1.4). See server.py.
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim

ENV PYTHONUNBUFFERED=true
LABEL org.opencontainers.image.source="https://github.com/archetype-pal/backend"

ARG APT_REFRESH=""
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

RUN groupadd -r htr && useradd -r -g htr htr

WORKDIR /deps
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-cache
ENV PATH="/deps/.venv/bin:$PATH"

# The recognition model, fetched once at build time from its Zenodo record
# (CC-BY 4.0) and checked against its SHA-256, which the service also checks
# at start: a reading always names the weights that made it. The segmenter,
# `blla`, ships inside the pinned Kraken package.
ENV HTR_MODEL_NAME="CATMuS Medieval 1.5.0" \
    HTR_MODEL_PATH=/models/catmus-medieval.mlmodel \
    HTR_MODEL_SHA256=d1c1fd46af4003b8cf9b18c7049f93f48a8df07f2cbdf29c1d407affe9e251bd
ADD --checksum=sha256:d1c1fd46af4003b8cf9b18c7049f93f48a8df07f2cbdf29c1d407affe9e251bd \
    https://zenodo.org/records/12743230/files/catmus-medieval.mlmodel ${HTR_MODEL_PATH}
RUN chmod 0644 ${HTR_MODEL_PATH}

# The letter models (W1.1) are trained on the corpus, so they are not baked in:
# `train_letters.py` writes them, and the service loads them from here if they
# are there. See letters.py.
ENV HTR_LETTERS_DIR=/models/letters

WORKDIR /app
COPY server.py letters.py train_letters.py selftest.py ./
# Fail the build if the service, as the user it runs as, does not work against
# the model it ships.
USER htr
RUN python -m unittest -q selftest

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
CMD ["python", "server.py"]
