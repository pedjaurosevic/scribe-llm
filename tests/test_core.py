import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter


class TestLLMAdapter:
    def test_adapter_init(self):
        adapter = LLMAdapter()
        assert adapter is not None
        assert adapter.base_url is not None
        assert adapter.model is not None

    def test_is_healthy(self):
        adapter = LLMAdapter()
        assert isinstance(adapter.is_healthy(), bool)

    def test_get_model_name(self):
        adapter = LLMAdapter()
        name = adapter.get_model_name()
        assert isinstance(name, str)
        assert len(name) > 0

    @pytest.mark.integration
    def test_complete_returns_string(self):
        adapter = LLMAdapter()
        messages = [{"role": "user", "content": "Hi"}]
        response = adapter.complete(messages, max_tokens=10)
        assert isinstance(response, str)


class TestScribeConfig:
    def test_config_defaults(self):
        config = ScribeConfig()
        assert config.base_url is not None
        assert config.base_url.startswith("http")

    def test_config_is_singleton_like(self):
        config1 = ScribeConfig()
        config2 = ScribeConfig()
        assert config1.base_url == config2.base_url

    def test_sme_and_rag_enabled(self):
        config = ScribeConfig()
        assert isinstance(config.sme_enabled, bool)
        assert isinstance(config.rag_enabled, bool)


class TestAdapterModelResolution:
    def test_explicit_model_is_used_as_is(self):
        from scribe.llm_adapter import LLMAdapter
        adapter = LLMAdapter(base_url="http://127.0.0.1:9/v1", model="gemma4:12b")
        assert adapter._request_model() == "gemma4:12b"

    def test_default_resolves_to_first_server_model(self):
        from unittest.mock import MagicMock

        from scribe.llm_adapter import LLMAdapter

        adapter = LLMAdapter(base_url="http://127.0.0.1:9/v1", model="default")
        listing = MagicMock()
        listing.data = [MagicMock(id="served-model")]
        adapter.client = MagicMock()
        adapter.client.models.list.return_value = listing

        assert adapter._request_model() == "served-model"
        # Cached: a second call must not hit the server again.
        adapter.client.models.list.side_effect = AssertionError("re-queried")
        assert adapter._request_model() == "served-model"

    def test_default_kept_when_server_unreachable(self):
        from unittest.mock import MagicMock

        from scribe.llm_adapter import LLMAdapter

        adapter = LLMAdapter(base_url="http://127.0.0.1:9/v1", model="default")
        adapter.client = MagicMock()
        adapter.client.models.list.side_effect = OSError("down")

        # Falls back to the placeholder (llama.cpp ignores it anyway) ...
        assert adapter._request_model() == "default"

        # ... and is retried, not cached, once the server comes back.
        listing = MagicMock()
        listing.data = [MagicMock(id="served-model")]
        adapter.client.models.list.side_effect = None
        adapter.client.models.list.return_value = listing
        assert adapter._request_model() == "served-model"


class TestAdapterFromConfig:
    def test_from_config_wires_all_connection_settings(self):
        from types import SimpleNamespace

        from scribe.llm_adapter import LLMAdapter

        cfg = SimpleNamespace(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            model="google/gemma-4-26b-it",
            request_timeout=123,
            reasoning=False,
        )
        adapter = LLMAdapter.from_config(cfg)
        assert adapter.base_url == "https://openrouter.ai/api/v1"
        assert adapter.api_key == "sk-or-test"
        assert adapter.model == "google/gemma-4-26b-it"
        assert adapter.timeout == 123
        assert adapter.enable_thinking is False

def _chunk(content=None, tool_calls=None, reasoning=None):
    """Build a fake streaming chunk shaped like a ChatCompletionChunk."""
    from types import SimpleNamespace

    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content=reasoning
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _adapter_with_stream(chunks):
    """An adapter whose client streams the given fake chunks."""
    from unittest.mock import MagicMock

    adapter = LLMAdapter(base_url="http://127.0.0.1:9/v1", model="m")
    adapter.client = MagicMock()
    adapter.client.chat.completions.create.return_value = iter(chunks)
    return adapter


class TestStreamingTurn:
    def test_prose_streams_through_unbuffered(self):
        adapter = _adapter_with_stream(
            [_chunk("Hello "), _chunk("world"), _chunk("!")]
        )
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        # Each prose chunk is yielded as it arrives, not collected at the end.
        assert events == [
            ("answer", "Hello "),
            ("answer", "world"),
            ("answer", "!"),
        ]

    def test_code_block_answer_is_not_swallowed(self):
        # An answer that STARTS with a code fence is prose, not a tool call —
        # it must stream once the gate sees the fence holds code, and the
        # leading chunk must not be misparsed as a tool call.
        adapter = _adapter_with_stream(
            [_chunk("```python\n"), _chunk("print(1)\n"), _chunk("```")]
        )
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        kinds = [k for k, _ in events]
        assert "tool_calls" not in kinds
        assert "".join(p for k, p in events if k == "answer") == "```python\nprint(1)\n```"

    def test_fenced_json_tool_call_is_parsed(self):
        adapter = _adapter_with_stream(
            [
                _chunk("```json\n"),
                _chunk('{"action": "list_dir", "action_input": {"path": "."}}'),
                _chunk("\n```"),
            ]
        )
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        assert events[-1][0] == "tool_calls"
        calls = events[-1][1]
        assert calls[0]["name"] == "list_dir"
        assert "answer" not in [k for k, _ in events]

    def test_bare_json_tool_call_is_parsed(self):
        adapter = _adapter_with_stream(
            [_chunk('{"name": "read_file", "arguments": {"path": "a.txt"}}')]
        )
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        assert events == [
            (
                "tool_calls",
                [
                    {
                        "id": "call_text_fallback",
                        "name": "read_file",
                        "arguments": '{"path": "a.txt"}',
                    }
                ],
            )
        ]

    def test_json_that_is_not_a_tool_call_is_released_as_answer(self):
        adapter = _adapter_with_stream([_chunk('{"just": "data"}')])
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        assert events == [("answer", '{"just": "data"}')]

    def test_think_block_split_from_answer(self):
        adapter = _adapter_with_stream(
            [_chunk("<think>plan</think>"), _chunk("Answer.")]
        )
        events = list(adapter.streaming_turn([{"role": "user", "content": "hi"}]))
        assert ("thinking", "plan") in events
        assert "".join(p for k, p in events if k == "answer") == "Answer."


class TestAsyncStreaming:
    def test_streaming_complete_async_yields_chunks(self):
        import asyncio

        adapter = _adapter_with_stream([_chunk("a"), _chunk("b"), _chunk("c")])

        async def collect():
            out = []
            async for chunk in adapter.streaming_complete_async(
                [{"role": "user", "content": "hi"}]
            ):
                out.append(chunk)
            return out

        assert asyncio.run(collect()) == ["a", "b", "c"]

    def test_streaming_turn_async_yields_tool_calls(self):
        import asyncio

        adapter = _adapter_with_stream(
            [_chunk('{"action": "list_dir", "action_input": {}}')]
        )

        async def collect():
            return [
                e
                async for e in adapter.streaming_turn_async(
                    [{"role": "user", "content": "hi"}]
                )
            ]

        events = asyncio.run(collect())
        assert events[-1][0] == "tool_calls"
        assert events[-1][1][0]["name"] == "list_dir"

    def test_producer_error_reaches_consumer(self):
        import asyncio
        from unittest.mock import MagicMock

        adapter = LLMAdapter(base_url="http://127.0.0.1:9/v1", model="m")
        adapter.client = MagicMock()
        adapter.client.chat.completions.create.side_effect = OSError("server down")

        async def collect():
            async for _ in adapter.streaming_complete_async(
                [{"role": "user", "content": "hi"}]
            ):
                pass

        with pytest.raises(OSError, match="server down"):
            asyncio.run(collect())


class TestReasoningDefaults:
    """Reasoning is OFF by default everywhere; /reasoning turns it on live."""

    def test_config_reasoning_off_by_default(self, tmp_path):
        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        assert cfg.reasoning is False
        assert cfg.reasoning_mode == "native"

    def test_direct_prompt_when_reasoning_off(self):
        from scribe.prompts import get_system_prompt

        prompt = get_system_prompt(reasoning=False)
        assert "Do NOT produce a <think> block" in prompt
        assert "How you think" not in prompt  # no reasoning instructions

    def test_native_prompt_when_reasoning_on(self):
        from scribe.prompts import get_system_prompt

        prompt = get_system_prompt(reasoning=True)
        assert "How you think (reasoning only)" in prompt
        assert "Start your output now" not in prompt  # not the forced variant

    def test_forced_prompt_when_reasoning_on_prompt_mode(self):
        from scribe.prompts import get_system_prompt

        prompt = get_system_prompt(reasoning=True, mode="prompt")
        assert "Start your output now with the literal characters <think>" in prompt

    def test_adapter_suppresses_thinking_by_default(self, tmp_path):
        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        adapter = LLMAdapter.from_config(cfg)
        adapter._grammar_supported = True  # llama.cpp fingerprint, no network probe
        assert adapter.enable_thinking is False
        kwargs = adapter._with_thinking({})
        assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
