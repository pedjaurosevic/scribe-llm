import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scribe.memory import RAGService, SMEService, get_rag_service, get_sme_service


class TestSMEService:
    def test_get_sme_service(self):
        sme = get_sme_service()
        assert sme is None or isinstance(sme, SMEService)

    @pytest.mark.integration
    def test_sme_service_operations(self):
        sme = get_sme_service()
        if sme is None:
            pytest.skip("SME not available")

        count_before = sme.count()

        entry_id = sme.add(
            content="Test entry for unit testing",
            topic="test",
            session_id="test-session-001"
        )
        assert entry_id is not None

        assert sme.count() == count_before + 1

        results = sme.search("test entry")
        assert len(results) > 0

        recent = sme.get_recent(limit=5)
        assert len(recent) > 0

        success = sme.delete(entry_id)
        assert success

        assert sme.count() == count_before


class TestRAGService:
    def test_get_rag_service(self):
        rag = get_rag_service()
        assert rag is None or isinstance(rag, RAGService)

    @pytest.mark.integration
    def test_rag_service_operations(self):
        rag = get_rag_service()
        if rag is None:
            pytest.skip("RAG not available")

        count_before = rag.count()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("This is a test document for RAG indexing. ")
            f.write("It contains multiple sentences to test chunking. ")
            f.write("The RAG system should split this into chunks.")
            temp_path = f.name

        try:
            chunks_added = rag.ingest_file(temp_path)
            assert chunks_added > 0

            assert rag.count() == count_before + chunks_added

            sources = rag.list_sources()
            assert len(sources) > 0

            results = rag.search("test document")
            assert len(results) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestIntegrationPaths:
    """The DB locations must come from config, never from hardcoded paths."""

    def test_sme_uses_own_path_by_default(self, tmp_path):
        from scribe.config import ScribeConfig

        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        cfg.set("scribe.sme", "db_path", str(tmp_path / "own-sme"))

        sme = get_sme_service(cfg)
        assert sme is not None
        assert sme.db_path == tmp_path / "own-sme"

    def test_sme_integration_path_wins_when_set(self, tmp_path):
        from scribe.config import ScribeConfig

        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        cfg.set("scribe.sme", "db_path", str(tmp_path / "own-sme"))
        cfg.set("scribe.integrations", "sme_path", str(tmp_path / "shared-sme"))

        sme = get_sme_service(cfg)
        assert sme is not None
        assert sme.db_path == tmp_path / "shared-sme"

    def test_rag_integration_path_wins_when_set(self, tmp_path):
        from scribe.config import ScribeConfig

        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        cfg.set("scribe.integrations", "rag_path", str(tmp_path / "shared-rag"))

        rag = get_rag_service(cfg)
        assert rag is not None
        assert rag.db_path == tmp_path / "shared-rag"

    def test_rag_uses_own_path_by_default(self, tmp_path):
        from scribe.config import ScribeConfig

        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        cfg.set("scribe.rag", "index_dir", str(tmp_path / "own-rag"))

        rag = get_rag_service(cfg)
        assert rag is not None
        assert rag.db_path == tmp_path / "own-rag"

    def test_paths_are_expanded(self, tmp_path):
        from scribe.config import ScribeConfig

        cfg = ScribeConfig(config_path=tmp_path / "missing.toml")
        cfg.set("scribe.integrations", "sme_path", "~/some-sme-dir")
        assert cfg.sme_db_path == str(Path.home() / "some-sme-dir")
        # Empty integration values fall back to the scribe.sme default.
        cfg.set("scribe.integrations", "sme_path", "")
        assert cfg.sme_db_path == str(Path.home() / ".scribe" / "sme")


def test_brave_env_file_from_config(tmp_path, monkeypatch):
    """load_brave_api_key reads the env file named in scribe.integrations."""
    import scribe.config as config_mod
    from scribe.tools import web

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    env_file = tmp_path / ".env.brave"
    env_file.write_text("BRAVE_API_KEY=key-from-env-file\n")

    cfg = config_mod.ScribeConfig(config_path=tmp_path / "missing.toml")
    cfg.set("scribe.integrations", "brave_env_file", str(env_file))
    monkeypatch.setattr(config_mod, "ScribeConfig", lambda: cfg)

    assert web.load_brave_api_key() == "key-from-env-file"
