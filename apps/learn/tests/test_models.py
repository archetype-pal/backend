"""A session's setup and transcript come back from the database as they were written.

Compared as JSON text, because dict equality does not see key order, and the
prompt cache does: Postgres's jsonb would hand these back with every object's
keys sorted.
"""

import json

import pytest

from apps.learn.models import TutorSession
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db


def stored(**fields) -> TutorSession:
    session: TutorSession = TutorSession.objects.get(
        pk=TutorSession.objects.create(item_image=ItemImageFactory(), **fields).pk
    )
    return session


class TestKeptAsWritten:
    def test_keys_come_back_in_the_order_they_were_written(self):
        setup = {
            "model": "claude-fable-5-1",
            "system": "You are the tutor.",
            "tools": [
                {
                    "name": "corpus_examples",
                    "input_schema": {"type": "object", "properties": {"reason": {}, "allograph_id": {}, "count": {}}},
                }
            ],
        }
        transcript = [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "corpus_examples",
                        "input": {"reason": "to compare", "allograph_id": 5, "count": 6},
                    },
                ],
            }
        ]

        session = stored(setup=setup, transcript=transcript)

        assert json.dumps(session.setup) == json.dumps(setup)
        assert json.dumps(session.transcript) == json.dumps(transcript)

    def test_text_in_any_script_comes_back_unchanged(self):
        text = "Das „tironische“ Zeichen ⁊, l’abréviation"
        transcript = [{"role": "user", "content": [{"type": "text", "text": text}]}]

        assert stored(transcript=transcript).transcript == transcript

    def test_a_new_session_has_an_empty_setup_and_transcript(self):
        session = stored()

        assert session.setup == {}
        assert session.transcript == []
