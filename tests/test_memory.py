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
