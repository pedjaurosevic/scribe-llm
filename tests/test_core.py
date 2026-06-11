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
