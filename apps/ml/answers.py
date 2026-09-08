"""Reading a model's answer.

Here rather than in whichever app happened to need it first: every pipeline in
the platform asks for JSON and every one of them gets a code fence some of the
time, so the tolerance belongs in one place. Nothing in this module knows about
the corpus, which is why it can live in the app that may not import a domain
app.
"""

import json
import re
from typing import Any

# Models fence JSON as often as not. Strip one fence rather than fail a whole
# corpus pass on punctuation.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_json(text: str) -> Any:
    """Parse a model's JSON answer, tolerating a code fence.

    Raises `ValueError` — never returns a partial reading. A pipeline records
    that as an unusable answer and moves on; a half-parsed one would become a
    proposal a human has to disprove.
    """
    fenced = _FENCE.match(text or "")
    payload = fenced.group(1) if fenced else (text or "")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return usable JSON: {exc}") from exc
