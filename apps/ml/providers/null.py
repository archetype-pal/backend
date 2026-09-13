"""A provider that runs no model.

It exists so the ledger, the budget guard, the task path and the management API
can all be exercised end to end — in tests and against a live stack — without a
model, a GPU, an API key or a network. Everything downstream of W0.1 is built
against this before it is built against anything real.
"""

import hashlib
import json
from typing import Any

from .base import InferenceRequest, InferenceResult


def content_digest(payload: Any) -> str:
    """Stable sha256 hex digest of any JSON-serialisable payload.

    Sorted keys so the digest is a function of the content, not of dict order —
    the same inputs must produce the same `input_ref` on every run, or the
    ledger cannot be used to find prior calls on the same evidence.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NullProvider:
    """Echoes its inputs back, and reports zero cost."""

    model_name = "null"
    model_version = "1"

    def run(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(
            output={"echo": dict(request.inputs), "task": request.task},
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_hash=content_digest(request.inputs),
        )
