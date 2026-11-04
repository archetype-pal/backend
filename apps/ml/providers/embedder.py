"""The self-hosted glyph encoder (AI programme W1.2), reached over HTTP.

The model runs in its own container (`embedder/`, beside this repository's
backend), on our own server: no image sent to it leaves our infrastructure.
That is why its registration says `hosted=False`. It is still behind
`ML_INFERENCE_ENABLED`, like every provider, and every call is a ledger row.

Inputs are `{"images": [<base64 PNG or JPEG>, ...]}`. The output is
`{"vectors": [[...], ...], "dimensions": n}`, one unit-length vector per image
in the order sent. The ledger records the model and revision the service
reports, so a stored vector can always be traced to the weights that made it.
Self-hosted inference has no per-call price, so the cost is 0.
"""

import json
from typing import Any
import urllib.error
import urllib.request

from django.conf import settings

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

# CPU inference on a batch of glyphs takes seconds, not minutes. A call that
# takes longer than this is a service in trouble, and a corpus pass should
# stop rather than queue behind it.
DEFAULT_TIMEOUT = 120


class EmbedderProvider:
    """Sends crops to the embedder service and checks what comes back."""

    def run(self, request: InferenceRequest) -> InferenceResult:
        base = str(getattr(settings, "ML_EMBEDDER_URL", "") or "").rstrip("/")
        if not base:
            raise ProviderError("ML_EMBEDDER_URL is not set: the self-hosted encoder is not configured.")
        images = request.inputs.get("images")
        if not isinstance(images, list) or not images or not all(isinstance(image, str) for image in images):
            raise ProviderError("The encoder takes a non-empty list of base64 images.")

        payload = self._post(f"{base}/embed", {"images": images}, timeout=self._timeout(request))
        vectors, dimensions = self._vectors(payload, expected=len(images))
        return InferenceResult(
            output={"vectors": vectors, "dimensions": dimensions},
            model_name=str(payload.get("model") or ""),
            model_version=str(payload.get("revision") or ""),
            prompt_hash=content_digest(images),
        )

    @staticmethod
    def _timeout(request: InferenceRequest) -> float:
        return float(request.params.get("timeout_seconds") or DEFAULT_TIMEOUT)

    @staticmethod
    def _post(url: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        http_request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                detail = exc.read(500).decode("utf-8", "replace")
            raise ProviderError(f"The encoder refused the request ({exc.code}): {detail}") from None
        except (OSError, ValueError) as exc:
            raise ProviderError(f"The encoder could not be reached or gave no JSON: {exc}") from None
        if not isinstance(payload, dict):
            raise ProviderError("The encoder's answer is not a JSON object.")
        return payload

    @staticmethod
    def _vectors(payload: dict[str, Any], *, expected: int) -> tuple[list[list[float]], int]:
        """The vectors, refused unless there is one of the stated length per image.

        A short or ragged answer would pair a vector with the wrong glyph, which
        is worse than no answer: nothing downstream could tell.
        """
        vectors = payload.get("vectors")
        dimensions = payload.get("dimensions")
        if not isinstance(dimensions, int) or dimensions < 1:
            raise ProviderError("The encoder did not say how long its vectors are.")
        if not isinstance(vectors, list) or len(vectors) != expected:
            got = len(vectors) if isinstance(vectors, list) else "no"
            raise ProviderError(f"The encoder returned {got} vectors for {expected} images.")
        checked = []
        for position, vector in enumerate(vectors):
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ProviderError(f"Vector {position} is not {dimensions} numbers long.")
            try:
                checked.append([float(value) for value in vector])
            except TypeError, ValueError:
                raise ProviderError(f"Vector {position} holds something that is not a number.") from None
        return checked, dimensions
