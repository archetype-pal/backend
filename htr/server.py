"""Self-hosted handwritten text recognition for charter pages (AI programme W1.4).

Kraken (Apache-2.0) reads a page in two steps, each with a model used as
published, neither trained on this corpus:

- its default baseline segmenter, `blla`, which ships with Kraken, finds the
  written lines;
- CATMuS Medieval 1.5.0 (CC-BY 4.0; Pinche, Clérice, Chagué, Camps,
  Vlachou-Efstathiou, Gille Levenson et al., doi:10.5281/zenodo.12743230),
  trained on medieval Latin and vernacular manuscripts, reads each line.

This is the off-the-shelf medieval-Latin baseline §7.2 measures the corpus
against. CATMuS transcribes graphemically: an abbreviation stays as the scribe
wrote it, its mark a combining character, and is not expanded.

It runs on the CPU of the server that hosts the rest of the stack and is reached
only over the stack's internal network, so no page leaves our infrastructure.
It is heavier than the embedder: the segmenter scales every page to one
height, and reading a 1,600-pixel page peaks at about 3.3 GB of memory.

`POST /read` takes `{"image": <base64 PNG or JPEG>}` and returns the lines in
reading order, each `{"text": ..., "box": [x, y, width, height]}` in the
image's pixels, with the models that read them. `GET /health` names the models
without running them.

`POST /letters` takes the same body and returns every character it read with
the box an expert would draw round it and the allograph it most likely is
(W1.1; see `letters.py`). It needs the letter models, which are trained on the
corpus and kept in `HTR_LETTERS_DIR`; without them it answers 503 and `/read`
works as before.

The recognition model is fetched when the image is built and checked against
its SHA-256, which is its revision: every reading names the exact weights that
made it. Kraken is pinned at 7.1.1, which warns that `blla.segment` and
`rpred` go in Kraken 8; move to its task models before upgrading.
"""

import base64
import binascii
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Self

from kraken import blla, rpred
from kraken.lib import models
import letters
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("htr")

MODEL_NAME = os.environ.get("HTR_MODEL_NAME", "CATMuS Medieval 1.5.0")
MODEL_PATH = Path(os.environ.get("HTR_MODEL_PATH", "/models/catmus-medieval.mlmodel"))
MODEL_SHA256 = os.environ.get("HTR_MODEL_SHA256", "")
LETTERS_DIR = Path(os.environ.get("HTR_LETTERS_DIR", "/models/letters"))

# Limits on one request: one page, as the image server renders it.
MAX_SIDE = 4000
MAX_BODY = 32 * 1024 * 1024


class BadRequest(ValueError):
    """The request cannot be read as sent. The message is safe to return."""


class NoLetterModels(RuntimeError):
    """The letter models are not installed. The message is safe to return."""


def decode(encoded: Any) -> Image.Image:
    """The request's page, as an RGB picture."""
    if not isinstance(encoded, str):
        raise BadRequest("The image is not a base64 string.")
    try:
        data = base64.b64decode(encoded, validate=True)
        image = Image.open(io.BytesIO(data))
        image.load()
    except (binascii.Error, UnidentifiedImageError, OSError) as exc:
        raise BadRequest(f"The image is not a PNG or JPEG image ({exc}).") from None
    if max(image.size) > MAX_SIDE:
        raise BadRequest(f"The image is {image.size[0]}×{image.size[1]}; send at most {MAX_SIDE}px a side.")
    if min(image.size) < 1:
        raise BadRequest("The image is empty.")
    return image.convert("RGB")


class Reader:
    """The recognition model, loaded once; one page read at a time."""

    def __init__(
        self, model: Any, *, name: str, revision: str, letter_models: letters.LetterModels | None = None
    ) -> None:
        self.model = model
        self.name = name
        self.revision = revision
        self.letter_models = letter_models
        # Kraken already spreads one page across every core. Taking turns keeps memory bounded under load.
        self._lock = threading.Lock()

    @classmethod
    def load(cls) -> Self:
        if not MODEL_SHA256:
            raise RuntimeError("HTR_MODEL_SHA256 is not set; refusing to run unpinned weights.")
        digest = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise RuntimeError(f"{MODEL_PATH} has SHA-256 {digest}, not {MODEL_SHA256}; rebuild the image.")
        found = None
        if (LETTERS_DIR / "letters.json").is_file():
            found = letters.LetterModels.load(LETTERS_DIR)
        return cls(models.load_any(str(MODEL_PATH)), name=MODEL_NAME, revision=MODEL_SHA256, letter_models=found)

    def read(self, page: Image.Image) -> list[dict[str, Any]]:
        """The page's lines in reading order, each with its box. A line read as nothing is left out."""
        with self._lock:
            return self.recognise(page, blla.segment(page))

    def recognise(self, page: Image.Image, segmentation: Any) -> list[dict[str, Any]]:
        """Read the lines `segmentation` found on `page`."""
        records = list(rpred.rpred(self.model, page, segmentation))
        lines = []
        for record in records:
            text = record.prediction.strip()
            if not text:
                continue
            xs = [x for x, _ in record.boundary]
            ys = [y for _, y in record.boundary]
            lines.append({"text": text, "box": [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]})
        return lines

    def find_letters(self, page: Image.Image) -> list[dict[str, Any]]:
        """Every character on the page, with its box and allograph, in the page's pixels."""
        if self.letter_models is None:
            raise NoLetterModels(f"No letter models are installed in {LETTERS_DIR}; see train_letters.py.")
        view, scale = letters.for_reading(page)
        with self._lock:
            records = list(rpred.rpred(self.model, view, blla.segment(view)))
            found = letters.anchors(letters.reading(records, scale=scale))
            return self.letter_models.find(page.convert("L"), found)

    def describe(self) -> dict[str, Any]:
        return {"model": self.name, "revision": self.revision, "segmenter": "kraken blla"}

    def describe_letters(self) -> dict[str, Any] | None:
        return self.letter_models.describe() if self.letter_models else None


def page_of(body: Any) -> Image.Image:
    """The page a request body sends."""
    if not isinstance(body, dict) or "image" not in body:
        raise BadRequest('Send {"image": <base64 image>}.')
    return decode(body["image"])


def read_request(reader: Reader, body: Any) -> dict[str, Any]:
    """Validate a request body and read its page."""
    return {**reader.describe(), "lines": reader.read(page_of(body))}


def letters_request(reader: Reader, body: Any) -> dict[str, Any]:
    """Validate a request body and find its page's letters."""
    page = page_of(body)
    return {
        **reader.describe(),
        "letter_models": reader.describe_letters(),
        "width": page.width,
        "height": page.height,
        "letters": reader.find_letters(page),
    }


def handler_for(reader: Reader) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "archetype-htr"

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found."})
                return
            self._send(HTTPStatus.OK, {**reader.describe(), "letter_models": reader.describe_letters()})

        def do_POST(self) -> None:
            answer = {"/read": read_request, "/letters": letters_request}.get(self.path)
            if answer is None:
                self._send(HTTPStatus.NOT_FOUND, {"detail": "Not found."})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": f"Bodies are limited to {MAX_BODY} bytes."})
                return
            started = time.monotonic()
            try:
                body = json.loads(self.rfile.read(length) or b"null")
                payload = answer(reader, body)
            except json.JSONDecodeError:
                self._send(HTTPStatus.BAD_REQUEST, {"detail": "The body is not JSON."})
                return
            except BadRequest as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"detail": str(exc)})
                return
            except NoLetterModels as exc:
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": str(exc)})
                return
            found = payload["lines"] if "lines" in payload else payload["letters"]
            logger.info("%s: %d found in %dms.", self.path, len(found), (time.monotonic() - started) * 1000)
            self._send(HTTPStatus.OK, payload)

        def log_message(self, format: str, *args: Any) -> None:
            # One line per page comes from `do_POST`; the access log adds nothing.
            return

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reader = Reader.load()
    port = int(os.environ.get("HTR_PORT") or 8080)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_for(reader))
    logger.info("Serving %s@%s on :%d.", reader.name, reader.revision[:12], port)
    if reader.letter_models:
        found = reader.letter_models
        logger.info("Finding letters with %s@%s.", found.describe()["name"], found.revision[:12])
    else:
        logger.info("No letter models in %s: /letters answers 503.", LETTERS_DIR)
    server.serve_forever()


if __name__ == "__main__":
    main()
