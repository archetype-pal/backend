"""A self-hosted image encoder for glyph crops (AI programme W1.2).

The vision half of a handwriting-recognition model trained on medieval Latin:
LaMOP's TrOCR_Manicule_2026_Latin_Medieval (MIT), which is
microsoft/trocr-base-handwritten fine-tuned on lines from medieval acts,
cartularies and manuscripts. Only its encoder runs here. The text decoder is
dropped when the image is built. A glyph's vector is the mean of the encoder's
patch tokens. The model is used as published: it has not been trained on this
corpus.

It runs on the CPU of the server that hosts the rest of the stack and is reached
only over the stack's internal network, so no image of a charter leaves our
infrastructure. That is why the backend registers it as a self-hosted
provider, behind `ML_INFERENCE_ENABLED` but not the hosted-provider switch.

`POST /embed` takes `{"images": [<base64 PNG or JPEG>, ...]}` and returns one
L2-normalised vector per image, in the order given, with the model and the
revision that made them. `GET /health` names the model without running it.

The weights are fetched when the image is built, at a pinned revision, and the
service runs with the Hugging Face Hub switched off. Every vector therefore
names the exact weights that made it.
"""

import base64
import binascii
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError
import torch
from transformers import ViTModel

logger = logging.getLogger("embedder")

MODEL_ID = os.environ.get("EMBEDDER_MODEL", "LaMOP/TrOCR_Manicule_2026_Latin_Medieval")
REVISION = os.environ.get("EMBEDDER_REVISION", "")
# Where the build saved the encoder alone, with a note of the checkpoint it came from.
ENCODER_PATH = Path(os.environ.get("EMBEDDER_ENCODER_PATH", "/models/encoder"))

# TrOCR reads 384 x 384 pictures in 16-pixel patches, scaled to [-1, 1].
SIZE = 384
MEAN = torch.tensor([0.5, 0.5, 0.5]).view(3, 1, 1)
STD = torch.tensor([0.5, 0.5, 0.5]).view(3, 1, 1)

# Limits on one request. A glyph crop is small; anything near these is a
# caller sending whole pages, which this service is not for.
MAX_IMAGES = 64
MAX_SIDE = 1024
MAX_BODY = 32 * 1024 * 1024
# Images per forward pass. Bounds memory, not throughput.
BATCH = 8


class BadRequest(ValueError):
    """The request cannot be embedded as sent. The message is safe to return."""


def edge_colour(image: Image.Image) -> tuple[int, int, int]:
    """The mean colour of the crop's outermost pixels: parchment, almost always."""
    width, height = image.size
    strips = [
        image.crop((0, 0, width, 1)),
        image.crop((0, height - 1, width, height)),
        image.crop((0, 0, 1, height)),
        image.crop((width - 1, 0, width, height)),
    ]
    sums = [0.0, 0.0, 0.0]
    count = 0
    for strip in strips:
        stat = ImageStat.Stat(strip)
        for band in range(3):
            sums[band] += stat.sum[band]
        count += strip.size[0] * strip.size[1]
    red, green, blue = (round(total / count) for total in sums)
    return red, green, blue


def fit(image: Image.Image) -> Image.Image:
    """Scale to fit `SIZE` square, centred, padded in the colour of the crop's own edges.

    A glyph is rarely square, and stretching one would change its shape, which
    is the thing being compared. Padding in the edge colour adds background
    rather than a frame the model would also see.
    """
    return ImageOps.pad(image, (SIZE, SIZE), method=Image.Resampling.BICUBIC, color=edge_colour(image))


def decode(encoded: Any, position: int) -> Image.Image:
    """One request image, as an RGB picture ready to fit."""
    if not isinstance(encoded, str):
        raise BadRequest(f"Image {position} is not a base64 string.")
    try:
        data = base64.b64decode(encoded, validate=True)
        image = Image.open(io.BytesIO(data))
        image.load()
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise BadRequest(f"Image {position} is not a PNG or JPEG image ({exc}).") from None
    if max(image.size) > MAX_SIDE:
        raise BadRequest(f"Image {position} is {image.size[0]}×{image.size[1]}; send glyphs, at most {MAX_SIDE}px.")
    if min(image.size) < 1:
        raise BadRequest(f"Image {position} is empty.")
    return image.convert("RGB")


def to_tensor(image: Image.Image) -> torch.Tensor:
    """Fit and normalise one picture as TrOCR's encoder expects."""
    picture = fit(image)
    pixels = torch.frombuffer(bytearray(picture.tobytes()), dtype=torch.uint8)
    tensor = pixels.reshape(SIZE, SIZE, 3).permute(2, 0, 1).float().div(255)
    return (tensor - MEAN) / STD


class Encoder:
    """The model, loaded once, run one batch at a time."""

    def __init__(self, model: torch.nn.Module, *, model_id: str, revision: str) -> None:
        self.model = model.eval()
        self.model_id = model_id
        self.revision = revision
        self.dimensions = int(model.config.hidden_size)
        # Forward passes share the model, and torch already spreads one pass
        # across every core. Taking turns keeps memory bounded under load.
        self._lock = threading.Lock()

    @classmethod
    def load(cls) -> Encoder:
        if not REVISION:
            raise RuntimeError("EMBEDDER_REVISION is not set; refusing to run unpinned weights.")
        source = json.loads((ENCODER_PATH / "source.json").read_text())
        if source != {"model": MODEL_ID, "revision": REVISION}:
            raise RuntimeError(
                f"The encoder at {ENCODER_PATH} came from {source}, not {MODEL_ID}@{REVISION}; rebuild the image."
            )
        model = ViTModel.from_pretrained(ENCODER_PATH, add_pooling_layer=False)
        return cls(model, model_id=MODEL_ID, revision=REVISION)

    def embed(self, images: list[Image.Image]) -> list[list[float]]:
        """One unit-length vector per image: the mean of the encoder's patch tokens."""
        vectors: list[list[float]] = []
        for start in range(0, len(images), BATCH):
            batch = torch.stack([to_tensor(image) for image in images[start : start + BATCH]])
            with self._lock, torch.inference_mode():
                hidden = self.model(pixel_values=batch).last_hidden_state
            # The first token is the class token; the rest are the picture's patches.
            pooled = hidden[:, 1:].mean(dim=1)
            unit = torch.nn.functional.normalize(pooled, dim=1)
            vectors.extend([[round(value, 6) for value in row] for row in unit.tolist()])
        return vectors

    def describe(self) -> dict[str, Any]:
        return {"model": self.model_id, "revision": self.revision, "dimensions": self.dimensions}


def embed_request(encoder: Encoder, body: Any) -> dict[str, Any]:
    """Validate a request body and embed it."""
    if not isinstance(body, dict) or not isinstance(body.get("images"), list):
        raise BadRequest('Send {"images": [<base64 image>, ...]}.')
    encoded = body["images"]
    if not encoded:
        raise BadRequest("No images to embed.")
    if len(encoded) > MAX_IMAGES:
        raise BadRequest(f"{len(encoded)} images in one request; send at most {MAX_IMAGES}.")
    images = [decode(item, position) for position, item in enumerate(encoded)]
    return {**encoder.describe(), "vectors": encoder.embed(images)}


def handler_for(encoder: Encoder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "archetype-embedder"

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found."})
                return
            self._send(HTTPStatus.OK, encoder.describe())

        def do_POST(self) -> None:
            if self.path != "/embed":
                self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found."})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": f"Bodies are limited to {MAX_BODY} bytes."})
                return
            started = time.monotonic()
            try:
                body = json.loads(self.rfile.read(length) or b"null")
                payload = embed_request(encoder, body)
            except json.JSONDecodeError:
                self._send(HTTPStatus.BAD_REQUEST, {"detail": "The body is not JSON."})
                return
            except BadRequest as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
                return
            logger.info("Embedded %d images in %dms.", len(payload["vectors"]), (time.monotonic() - started) * 1000)
            self._send(HTTPStatus.OK, payload)

        def log_message(self, format: str, *args: Any) -> None:
            # One line per embed comes from `do_POST`; the access log adds nothing.
            return

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    threads = int(os.environ.get("EMBEDDER_THREADS") or 0)
    if threads:
        torch.set_num_threads(threads)
    encoder = Encoder.load()
    port = int(os.environ.get("EMBEDDER_PORT") or 8080)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_for(encoder))
    logger.info("Serving %s@%s (%d-d) on :%d.", encoder.model_id, encoder.revision, encoder.dimensions, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
