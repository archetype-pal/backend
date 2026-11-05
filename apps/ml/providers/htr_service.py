"""Self-hosted handwritten text recognition (AI programme W1.4), reached over HTTP.

Kraken, with CATMuS Medieval, runs in its own container (`htr/`, beside this
repository's backend) on our own server: no page sent to it leaves our
infrastructure, which is why its registration says `hosted=False`. It is still
behind `ML_INFERENCE_ENABLED`, like every provider, and every call is a ledger
row.

It takes what the HTR harness sends any provider, `{"images": [<one page as a
data URL>], ...}`, and reads only the page: the model takes no prompt. It
answers as a hosted model is asked to, `text` holding `{"lines": [...]}` as
JSON, so `apps.vision.services.htr` parses either the same way; each line's box
on the page comes with it as `boxes`. The ledger records the model and the
SHA-256 of the weights the service reports. Self-hosted inference has no
per-call price, so the cost is 0.
"""

import json
from typing import Any
import urllib.error
import urllib.request

from django.conf import settings

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

# Finding and reading a page's lines on CPU takes seconds, not minutes. A call
# that takes longer than this is a service in trouble.
DEFAULT_TIMEOUT = 300


class HtrServiceProvider:
    """Sends a page to the HTR service and checks the lines that come back."""

    def run(self, request: InferenceRequest) -> InferenceResult:
        base = str(getattr(settings, "ML_HTR_URL", "") or "").rstrip("/")
        if not base:
            raise ProviderError("ML_HTR_URL is not set: the self-hosted reader is not configured.")
        images = request.inputs.get("images")
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
            raise ProviderError("The reader takes exactly one page image.")
        # The harness sends a data URL; the service takes the base64 after its comma.
        encoded = images[0].partition("base64,")[2] or images[0]

        timeout = float(request.params.get("timeout_seconds") or DEFAULT_TIMEOUT)
        payload = self._post(f"{base}/read", {"image": encoded}, timeout=timeout)
        lines = self._lines(payload)
        return InferenceResult(
            output={
                "text": json.dumps({"lines": [line["text"] for line in lines], "notes": ""}, ensure_ascii=False),
                "boxes": [line["box"] for line in lines],
            },
            model_name=str(payload.get("model") or ""),
            model_version=str(payload.get("revision") or ""),
            prompt_hash=content_digest([encoded]),
        )

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
            raise ProviderError(f"The reader refused the request ({exc.code}): {detail}") from None
        except (OSError, ValueError) as exc:
            raise ProviderError(f"The reader could not be reached or gave no JSON: {exc}") from None
        if not isinstance(payload, dict):
            raise ProviderError("The reader's answer is not a JSON object.")
        return payload

    @staticmethod
    def _lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """The lines, refused unless each is a reading with a box of four numbers."""
        lines = payload.get("lines")
        if not isinstance(lines, list):
            raise ProviderError("The reader's answer has no list of lines.")
        for position, line in enumerate(lines):
            box = line.get("box") if isinstance(line, dict) else None
            if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                raise ProviderError(f"Line {position} has no reading.")
            if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, int | float) for v in box):
                raise ProviderError(f"Line {position} has no box of four numbers.")
        return lines
