"""
Automated ablation / Clever-Hans test for Provenance World Model.
"""

from __future__ import annotations

import pytest

from scribe.config import ScribeConfig
from scribe.llm_adapter import LLMAdapter
from scribe.memory.provenance import ClaimStore, run_provenance_loop


@pytest.mark.asyncio
async def test_provenance_ablation(tmp_path, monkeypatch):
    # Initialize ScribeConfig and LLMAdapter against the live model endpoint
    config = ScribeConfig()
    adapter = LLMAdapter.from_config(config)

    if not adapter.is_healthy():
        pytest.skip("LLM server is not running or healthy at " + adapter.base_url)

    # Initialize a temporary ClaimStore
    db_file = tmp_path / "test_claims.db"
    claim_store = ClaimStore(db_path=db_file)

    try:
        # Mock web content dict
        mock_web_pages = {
            "http://scribeland-secret.local": (
                "The secret password for ScribeLand is Antigravity42."
            ),
            "http://scribeland-apples.local": "Apples are usually red, green, or yellow."
        }

        def mock_web_fetch(url: str) -> str:
            return mock_web_pages.get(url, "404 Not Found")

        # Apply monkeypatch to mock web_fetch
        monkeypatch.setattr("scribe.memory.provenance.web_fetch", mock_web_fetch)

        # ==========================================
        # Case (a): Factual question WITH the relevant page fetched
        # ==========================================
        query = "Find the secret password for ScribeLand by fetching http://scribeland-secret.local"

        # We start the loop, allowing the agent to fetch the secret URL.
        # The agent should call fetch/navigate to 'http://scribeland-secret.local'
        # and then return a final answer citing the correct span.
        formatted_answer, new_claims = await run_provenance_loop(
            adapter,
            query,
            claim_store,
            max_steps=3
        )

        print("--- Case (a) Answer ---")
        print(formatted_answer)
        print("Claims added:", new_claims)

        # Assert correct grounded answer
        assert "Antigravity42" in formatted_answer
        assert "[s1_1]" in formatted_answer
        assert len(new_claims) > 0
        assert new_claims[0]["text"] is not None

        # Verify that the claim exists in the ClaimStore
        searched = claim_store.search("password for ScribeLand", limit=1)
        assert len(searched) == 1
        assert "Antigravity42" in searched[0]["text"]

        # ==========================================
        # Case (b): Factual question WITHOUT the relevant page fetched
        # ==========================================
        # We clear the claim store first to remove case (a)'s memory
        claim_store.clear()

        # We query the password but point the agent to the apples page instead of the secret page
        # The agent will only fetch the apples page, and should refuse to guess the password.
        def mock_web_fetch_apples_only(url: str) -> str:
            # Re-route all fetches to apples page so secret page cannot be read
            return mock_web_pages["http://scribeland-apples.local"]

        monkeypatch.setattr("scribe.memory.provenance.web_fetch", mock_web_fetch_apples_only)

        formatted_answer_b, new_claims_b = await run_provenance_loop(
            adapter,
            query,
            claim_store,
            max_steps=3
        )

        print("--- Case (b) Answer ---")
        print(formatted_answer_b)
        print("Claims added B:", new_claims_b)

        # Assert empty-retrieval honesty: should not guess "Antigravity42" from priors,
        # and should refuse or state it is not in the sources.
        assert "Antigravity42" not in formatted_answer_b
        assert (
            "The sources do not contain this information" in formatted_answer_b
            or "[BLOCKED" in formatted_answer_b
        )
        assert len(new_claims_b) == 0

    finally:
        claim_store.close()
