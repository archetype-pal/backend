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

# The weights, fetched once at build time at a pinned revision (MIT), then the
# Hub is switched off: a vector always names the weights that made it. Only the
# vision encoder is kept (about a quarter of the checkpoint); the text decoder
# is never run. A note of the checkpoint it came from is saved beside it, and
# the service will not start if that disagrees with what it is told to run.
ENV EMBEDDER_MODEL=LaMOP/TrOCR_Manicule_2026_Latin_Medieval \
    EMBEDDER_REVISION=08e146d2dbf4673da24ce2f2dc5f3343bc62099c \
    EMBEDDER_ENCODER_PATH=/models/encoder \
    HF_HOME=/models/hub
RUN <<'PY' python
import json, os, shutil
from pathlib import Path
from huggingface_hub import snapshot_download
from transformers import VisionEncoderDecoderModel

model, revision = os.environ["EMBEDDER_MODEL"], os.environ["EMBEDDER_REVISION"]
checkpoint = snapshot_download(model, revision=revision, allow_patterns=["config.json", "model.safetensors"])
target = Path(os.environ["EMBEDDER_ENCODER_PATH"])
VisionEncoderDecoderModel.from_pretrained(checkpoint).encoder.save_pretrained(target)
(target / "source.json").write_text(json.dumps({"model": model, "revision": revision}))
# save_pretrained writes the weights readable by their owner only; the service runs as another user.
for path in target.iterdir():
    path.chmod(0o644)
shutil.rmtree(os.environ["HF_HOME"])
PY
ENV HF_HUB_OFFLINE=1

WORKDIR /app
COPY server.py selftest.py ./
# Fail the build if the service, as the user it runs as, does not work against
# the weights it ships.
USER embedder
RUN python -m unittest -q selftest

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
CMD ["python", "server.py"]
