"""The hosted Claude provider — the first that calls a real model.

Every test here mocks the SDK. A test that made a live call would spend money on
every CI run and fail without a key, and neither is a property worth pinning.
What is worth pinning is that the provider reports honestly to the ledger, and
that it stays refused until someone turns it on.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, resolve_provider
from apps.ml.providers.claude import PRICING, ClaudeProvider, estimate_cost_micros
from apps.ml.providers.null import content_digest
from apps.ml.services import InferenceService


def _response(*, text="Sanctio clause identified.", stop_reason="end_turn", model=None, **usage):
    return SimpleNamespace(
        id="msg_01ABC",
        model=model,
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 1000),
            output_tokens=usage.get("output_tokens", 200),
            cache_read_input_tokens=usage.get("cache_read", 0),
            cache_creation_input_tokens=usage.get("cache_write", 0),
            cache_creation=usage.get("cache_creation"),
        ),
    )


def _sdk(response=None, error=None):
    """A stand-in for the `anthropic` module, with the error classes it raises."""

    class _Err(Exception):
        status_code = 500
        type = "api_error"

    module = SimpleNamespace(
        NotFoundError=type("NotFoundError", (_Err,), {}),
        RateLimitError=type("RateLimitError", (_Err,), {}),
        APIStatusError=type("APIStatusError", (_Err,), {}),
        APIConnectionError=type("APIConnectionError", (_Err,), {}),
    )
    # The provider streams: `stream(...)` is a context manager whose final
    # message is the response. `create` is there to show it is never used.
    opened = mock.MagicMock()
    opened.__enter__.return_value.get_final_message.return_value = response
    stream = mock.Mock(side_effect=error) if error else mock.Mock(return_value=opened)
    create = mock.Mock()
    module.Anthropic = mock.Mock(
        return_value=SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream, create=create)))
    )
    module._stream, module._create = stream, create
    return module


class TestPricing:
    def test_cost_is_integer_micros(self):
        # 1000 in + 200 out on Opus 5 at $5/$25 per MTok.
        assert estimate_cost_micros("claude-opus-5", 1000, 200) == 1000 * 5 + 200 * 25

    def test_an_unpriced_model_is_charged_the_dearest_price_so_it_still_meets_a_cap(self):
        dearest = max(estimate_cost_micros(model, 1000, 200) for model in PRICING)

        assert estimate_cost_micros("some-future-model", 1000, 200) == dearest

    @pytest.mark.parametrize(
        ("model", "dollars_in", "dollars_out"),
        [
            ("claude-fable-5-1", 10, 50),
            ("claude-fable-5", 10, 50),
            ("claude-opus-5-5", 4, 20),
            ("claude-opus-4-8", 5, 25),
            ("claude-sonnet-5-5", 2, 10),
            ("claude-sonnet-5", 2, 10),
            ("claude-haiku-4-5", 1, 5),
        ],
    )
    def test_each_current_model_is_priced_at_its_list_price(self, model, dollars_in, dollars_out):
        # A million tokens each way costs the list price, in micro-dollars.
        assert estimate_cost_micros(model, 1_000_000, 0) == dollars_in * 1_000_000
        assert estimate_cost_micros(model, 0, 1_000_000) == dollars_out * 1_000_000

    def test_a_price_below_a_micro_dollar_a_token_is_kept(self):
        # Haiku 5.5: $0.10 and $0.50 per million tokens.
        assert estimate_cost_micros("claude-haiku-5-5", 1000, 200) == 100 + 100
        assert estimate_cost_micros("claude-haiku-5-5", 1_000_000, 1_000_000) == 600_000

    def test_a_fraction_of_a_micro_dollar_is_rounded_up(self):
        assert estimate_cost_micros("claude-haiku-5-5", 1, 0) == 1
        assert estimate_cost_micros("claude-haiku-5-5", 10, 1) == 2

    def test_a_cache_read_costs_a_tenth_of_an_input_token(self):
        # Fable 5.1 at $10 per million input tokens: a million read from the cache is $1.
        assert estimate_cost_micros("claude-fable-5-1", 0, 0, cache_reads=1_000_000) == 1_000_000

    def test_a_write_to_the_five_minute_cache_costs_a_quarter_more(self):
        assert estimate_cost_micros("claude-fable-5-1", 0, 0, cache_writes_5m=1_000_000) == 12_500_000

    def test_a_write_to_the_hours_cache_costs_double(self):
        assert estimate_cost_micros("claude-fable-5-1", 0, 0, cache_writes_1h=1_000_000) == 20_000_000

    def test_every_kind_of_token_adds_to_the_cost(self):
        # Opus 5 at $5/$25: 1000 uncached in, 2000 read, 400 written for five
        # minutes, 100 for the hour, and 200 out.
        expected = 1000 * 5 + 2000 * 5 // 10 + 400 * 5 * 5 // 4 + 100 * 5 * 2 + 200 * 25
        assert (
            estimate_cost_micros("claude-opus-5", 1000, 200, cache_reads=2000, cache_writes_5m=400, cache_writes_1h=100)
            == expected
        )

    def test_a_cached_fraction_of_a_micro_dollar_is_rounded_up(self):
        # Haiku 5.5: one cached read is a hundredth of a micro-dollar.
        assert estimate_cost_micros("claude-haiku-5-5", 0, 0, cache_reads=1) == 1


class TestTheCall:
    def _run(self, module, inputs=None):
        with mock.patch.dict("sys.modules", {"anthropic": module}):
            return ClaudeProvider().run(InferenceRequest(task="W2.1", inputs=inputs or {"prompt": "Find the sanctio."}))

    def test_reports_model_tokens_and_cost_to_the_ledger(self):
        module = _sdk(_response())

        result = self._run(module)

        assert result.model_name == "claude-opus-5-5"
        assert result.model_version == "msg_01ABC"
        assert result.input_tokens == 1000
        assert result.output_tokens == 200
        assert result.cost_micros == 1000 * 4 + 200 * 20
        assert result.cost_currency == "USD"
        assert result.output["text"] == "Sanctio clause identified."

    def test_cached_tokens_are_counted_and_priced_at_their_rates(self):
        module = _sdk(_response(cache_read=500, cache_write=300))

        result = self._run(module)

        assert result.input_tokens == 1000 + 500 + 300
        # Opus 5.5 at $4/$20: a read at a tenth, a five-minute write at a quarter more.
        assert result.cost_micros == 1000 * 4 + 500 * 4 // 10 + -(-300 * 4 * 5 // 4) + 200 * 20

    def test_a_write_to_the_hours_cache_is_priced_as_one(self):
        split = SimpleNamespace(ephemeral_5m_input_tokens=100, ephemeral_1h_input_tokens=200)
        module = _sdk(_response(input_tokens=0, output_tokens=0, cache_write=300, cache_creation=split))

        result = self._run(module)

        assert result.input_tokens == 300
        assert result.cost_micros == -(-(100 * 4 * 5) // 4) + 200 * 4 * 2

    def test_the_prompt_is_hashed_not_returned(self):
        module = _sdk(_response())

        result = self._run(module, {"prompt": "corpus text here", "system": "You are a diplomatist."})

        assert len(result.prompt_hash) == 64
        assert "corpus text" not in result.prompt_hash

    def test_a_refusal_is_an_error_not_an_empty_answer(self):
        """A refusal returns HTTP 200; reading .content would yield nothing."""
        module = _sdk(_response(text="", stop_reason="refusal"))

        with pytest.raises(ProviderError, match="declined") as refused:
            self._run(module)

        # Billed all the same, and the caps read the cost from the ledger.
        assert (refused.value.input_tokens, refused.value.output_tokens) == (1000, 200)
        assert refused.value.cost_micros > 0

    def test_a_missing_prompt_is_refused_before_any_call(self):
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="needs a 'prompt'"):
            self._run(module, {"system": "only a system prompt"})

        module._stream.assert_not_called()

    def test_adaptive_thinking_and_fallbacks_are_requested(self):
        module = _sdk(_response())

        self._run(module)

        payload = module._stream.call_args.kwargs
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["fallbacks"] == "default"

    def test_a_call_given_a_time_limit_gets_that_long_once(self):
        module = _sdk(_response())

        with mock.patch.dict("sys.modules", {"anthropic": module}):
            ClaudeProvider().run(
                InferenceRequest(task="W2.1", inputs={"prompt": "Find it."}, params={"timeout_seconds": 20})
            )

        assert module.Anthropic.call_args.kwargs == {"timeout": 20.0, "max_retries": 0}

    def test_a_call_without_one_keeps_the_sdk_defaults(self):
        module = _sdk(_response())

        self._run(module)

        assert module.Anthropic.call_args.kwargs == {}

    def test_the_call_is_streamed(self):
        """A page read with adaptive thinking can outlast an unstreamed request."""
        module = _sdk(_response())

        self._run(module)

        module._stream.assert_called_once()
        module._create.assert_not_called()

    def test_images_go_before_the_prompt_as_content_blocks(self):
        module = _sdk(_response())

        self._run(
            module,
            {
                "prompt": "Transcribe this charter.",
                "images": ["data:image/jpeg;base64,cGFnZQ==", "https://iiif.example/page/full/1600,/0/default.jpg"],
            },
        )

        (message,) = module._stream.call_args.kwargs["messages"]
        assert message["role"] == "user"
        assert message["content"] == [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "cGFnZQ=="}},
            {"type": "image", "source": {"type": "url", "url": "https://iiif.example/page/full/1600,/0/default.jpg"}},
            {"type": "text", "text": "Transcribe this charter."},
        ]

    def test_without_images_the_prompt_is_sent_as_text(self):
        module = _sdk(_response())

        self._run(module)

        (message,) = module._stream.call_args.kwargs["messages"]
        assert message["content"] == "Find the sanctio."

    @pytest.mark.parametrize(
        "url", ["data:text/plain;base64,cGFnZQ==", "data:image/png,rawbytes", "data:image/png;base64,", "ftp://x/y.png"]
    )
    def test_an_image_that_is_not_one_is_refused_before_any_call(self, url):
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="image"):
            self._run(module, {"prompt": "Transcribe this.", "images": [url]})

        module._stream.assert_not_called()

    def test_the_hash_covers_the_images_and_is_unchanged_without_them(self):
        def hashed(inputs):
            return self._run(_sdk(_response()), inputs).prompt_hash

        plain = {"prompt": "Transcribe this.", "system": "Diplomatic."}
        one = {**plain, "images": ["data:image/jpeg;base64,cGFnZQ=="]}
        other = {**plain, "images": ["data:image/jpeg;base64,b3RoZXI="]}

        assert hashed(plain) == content_digest({"system": "Diplomatic.", "prompt": "Transcribe this."})
        assert len({hashed(plain), hashed(one), hashed(other)}) == 3

    def test_the_model_that_answered_is_recorded_and_priced(self):
        """A refusal fallback can hand the call to another model."""
        module = _sdk(_response(model="claude-sonnet-5"))

        result = self._run(module, {"prompt": "Find the sanctio.", "model": "claude-opus-5"})

        assert module._stream.call_args.kwargs["model"] == "claude-opus-5"
        assert result.model_name == "claude-sonnet-5"
        assert result.cost_micros == 1000 * 2 + 200 * 10

    def test_a_conversation_is_sent_as_given_with_its_tools(self):
        module = _sdk(_response())
        conversation = [
            {"role": "user", "content": [{"type": "text", "text": "What is this letter?"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "tool_use", "id": "toolu_1", "name": "look_closer", "input": {"x": 1}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "a crop"}]},
        ]
        tools = [{"name": "look_closer", "description": "Zoom in.", "input_schema": {"type": "object"}}]

        self._run(module, {"messages": conversation, "tools": tools, "system": "You are a tutor."})

        payload = module._stream.call_args.kwargs
        assert payload["messages"] == conversation
        assert payload["tools"] == tools
        assert payload["system"] == "You are a tutor."

    def test_a_conversation_is_cached_from_one_turn_to_the_next(self):
        module = _sdk(_response())

        self._run(module, {"messages": [{"role": "user", "content": "Teach me."}]})

        assert module._stream.call_args.kwargs["cache_control"] == {"type": "ephemeral"}

    def test_a_conversation_drops_thinking_that_no_longer_binds_rather_than_fail(self):
        module = _sdk(_response())

        self._run(module, {"messages": [{"role": "user", "content": "Teach me."}]})

        payload = module._stream.call_args.kwargs
        assert payload["thinking"] == {
            "type": "adaptive",
            "block_binding": {"prefix_mismatch_behavior": "drop_block"},
        }
        # The setting is refused without its beta, and the fallbacks keep theirs.
        assert payload["betas"] == ["server-side-fallback-2026-07-01", "thinking-binding-controls-2026-08-01"]

    def test_a_single_prompt_is_neither_cached_nor_bound(self):
        module = _sdk(_response())

        self._run(module)

        payload = module._stream.call_args.kwargs
        assert "cache_control" not in payload
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["betas"] == ["server-side-fallback-2026-07-01"]

    def test_thinking_the_api_dropped_is_reported_and_logged(self, caplog):
        response = _response()
        response.input_transformations = [
            SimpleNamespace(type="thinking_dropped", path="messages.1.content.0", reason="prefix_binding_mismatch")
        ]
        module = _sdk(response)

        with caplog.at_level("WARNING", logger="apps.ml.providers.claude"):
            result = self._run(module, {"messages": [{"role": "user", "content": "Teach me."}]})

        assert result.output["input_transformations"] == [
            {"type": "thinking_dropped", "path": "messages.1.content.0", "reason": "prefix_binding_mismatch"}
        ]
        assert "messages.1.content.0" in caplog.text
        assert "prefix_binding_mismatch" in caplog.text

    def test_nothing_dropped_reports_nothing(self):
        result = self._run(_sdk(_response()), {"messages": [{"role": "user", "content": "Teach me."}]})

        assert result.output["input_transformations"] == []

    def test_a_tool_choice_is_sent_with_the_tools(self):
        module = _sdk(_response())
        tools = [{"name": "look_closer", "description": "Zoom in.", "input_schema": {"type": "object"}}]

        self._run(module, {"prompt": "Read.", "tools": tools, "tool_choice": {"type": "none"}})

        assert module._stream.call_args.kwargs["tool_choice"] == {"type": "none"}

    def test_without_tools_none_are_sent(self):
        module = _sdk(_response())

        self._run(module)

        assert "tools" not in module._stream.call_args.kwargs

    def test_tool_calls_and_the_blocks_to_replay_come_back(self):
        thinking = SimpleNamespace(type="thinking", thinking="", signature="sig-1")
        call = SimpleNamespace(type="tool_use", id="toolu_2", name="corpus_examples", input={"allograph_id": 7})
        note = SimpleNamespace(type="text", text="Let me compare.", citations=None)
        response = _response()
        response.content = [thinking, note, call]
        module = _sdk(response)

        result = self._run(module, {"messages": [{"role": "user", "content": "Teach me."}]})

        assert result.output["tool_calls"] == [
            {"id": "toolu_2", "name": "corpus_examples", "input": {"allograph_id": 7}}
        ]
        assert result.output["content"] == [
            {"type": "thinking", "thinking": "", "signature": "sig-1"},
            {"type": "text", "text": "Let me compare."},
            {"type": "tool_use", "id": "toolu_2", "name": "corpus_examples", "input": {"allograph_id": 7}},
        ]
        assert result.output["text"] == "Let me compare."

    def test_an_sdk_block_is_replayed_as_the_sdk_serialises_it(self):
        block = mock.Mock(type="text", text="ok")
        block.model_dump.return_value = {"type": "text", "text": "ok"}
        response = _response()
        response.content = [block]
        module = _sdk(response)

        result = self._run(module)

        block.model_dump.assert_called_once_with(mode="json", exclude_none=True)
        assert result.output["content"] == [{"type": "text", "text": "ok"}]

    def test_a_conversations_hash_covers_its_messages_and_tools(self):
        def hashed(inputs):
            return self._run(_sdk(_response()), inputs).prompt_hash

        one = {"messages": [{"role": "user", "content": "a"}]}
        other = {"messages": [{"role": "user", "content": "b"}]}
        with_tools = {**one, "tools": [{"name": "t", "description": "", "input_schema": {"type": "object"}}]}

        assert len({hashed(one), hashed(other), hashed(with_tools)}) == 3

    def test_neither_a_prompt_nor_a_conversation_is_refused(self):
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="'prompt' or 'messages'"):
            self._run(module, {"tools": []})

        module._stream.assert_not_called()

    @pytest.mark.parametrize("kind", ["NotFoundError", "RateLimitError", "APIStatusError", "APIConnectionError"])
    def test_sdk_errors_become_provider_errors(self, kind):
        """The ledger records a failure; it never sees an SDK exception type."""
        module = _sdk()
        module._stream.side_effect = getattr(module, kind)("boom")

        with pytest.raises(ProviderError):
            self._run(module)


@pytest.mark.django_db
class TestItStaysOffByDefault:
    def test_the_provider_is_registered_as_hosted(self):
        assert resolve_provider("claude").hosted is True

    def test_it_is_refused_while_the_data_policy_gate_is_shut(self, settings):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_HOSTED_PROVIDERS_ENABLED = False

        job = InferenceService().submit(task="W2.1", provider="claude", inputs={"prompt": "hello"})

        assert job.status == MLJob.Status.REFUSED
        assert "hosted" in job.error
