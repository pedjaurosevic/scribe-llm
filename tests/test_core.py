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
