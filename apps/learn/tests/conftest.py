"""Shared fixtures for the tutor's tests.

Every test drives a scripted provider through the real inference service, so
the ledger and the switches are exercised; none calls a model. The pictures
the tutor keeps go to a temporary directory, and throttle history is cleared
between tests, as the public agent's tests clear it.
"""

import io
from unittest import mock

from django.core.cache import cache
from PIL import Image, ImageDraw
import pytest

from apps.ml.providers import InferenceRequest, InferenceResult


@pytest.fixture(autouse=True)
def _learn_storage(settings, tmp_path):
    settings.LEARN_STORAGE_DIR = str(tmp_path / "learn")


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 10_000_000
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


def jpeg(width=800, height=600, *, fmt="JPEG", mode="RGB", exif_orientation=None) -> bytes:
    """A picture with a dark bar at its top left, so that a turn or a crop can be seen in its pixels."""
    image = Image.new(mode, (width, height), "white")
    ImageDraw.Draw(image).rectangle((0, 0, width // 4, height // 8), fill="black")
    buffer = io.BytesIO()
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.save(buffer, fmt, exif=exif)
    else:
        image.save(buffer, fmt)
    return buffer.getvalue()


def ring(left, lower, right, upper):
    """A stored annotation: a Y-up ring in the full-size page's pixels."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[left, lower], [right, lower], [right, upper], [left, upper], [left, lower]]],
        },
    }


class Scripted:
    """Returns a prepared sequence of turns, then repeats the last one, recording what it was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests: list[InferenceRequest] = []

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        turn = self.turns[min(len(self.requests) - 1, len(self.turns) - 1)]
        if isinstance(turn, Exception):
            raise turn
        return InferenceResult(output=turn, model_name="claude-fable-5-1", cost_micros=11)


def turn(*calls, text="", stop_reason="tool_use"):
    """One model turn: its content blocks as the provider returns them, and its tool calls."""
    content = [{"type": "thinking", "thinking": "", "signature": f"sig-{len(calls)}"}]
    if text:
        content.append({"type": "text", "text": text})
    content += [{"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["input"]} for call in calls]
    return {
        "text": text,
        "stop_reason": stop_reason if calls else "end_turn" if stop_reason == "tool_use" else stop_reason,
        "content": content,
        "tool_calls": list(calls),
        "input_transformations": [],
    }


def call(name, arguments, call_id="toolu_1"):
    return {"id": call_id, "name": name, "input": arguments}


def stub(turns):
    provider = Scripted(turns)
    registration = mock.Mock(hosted=True, factory=lambda: provider)
    registration.name = "claude"
    return provider, mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)
