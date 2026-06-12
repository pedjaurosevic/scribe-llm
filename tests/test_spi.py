"""Tests for the SPI grounding metric and the grounded bench harness."""

from __future__ import annotations

from scribe.evolve.evaluate import (
    GROUNDED_FILE,
    MANIFEST_FILE,
    verify_manifest,
)
from scribe.evolve.spi import (
    evaluate_grounded,
    is_refusal,
    load_grounded_tasks,
    spi_score,
    split_sentences,
)


class TestSentenceSplit:
    def test_basic_split(self):
        assert split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]

    def test_bullets_and_headings(self):
        text = "# Heading\n- First point [1]. Second point [2]."
        sentences = split_sentences(text)
        assert "# Heading" not in sentences
        assert any("First point" in s for s in sentences)


class TestRefusal:
    def test_english_refusal(self):
        assert is_refusal("The sources do not cover this.")

    def test_serbian_refusal(self):
        assert is_refusal("Izvori ne pokrivaju ovo pitanje.")

    def test_answer_is_not_refusal(self):
        assert not is_refusal("The server listens on port 18083 [1].")


class TestSPIScore:
    def test_fully_cited_answer_scores_one(self):
        answer = "The port is 18083 [1]. The model is gemma-4-12B [1]."
        assert spi_score(answer, n_sources=2)["spi"] == 1.0

    def test_uncited_claim_lowers_score(self):
        answer = "The port is 18083 [1]. The sky is blue."
        assert spi_score(answer, n_sources=2)["spi"] == 0.5

    def test_out_of_range_citation_counts_as_uncited(self):
        answer = "The budget is huge [7]."
        score = spi_score(answer, n_sources=2)
        assert score["spi"] == 0.0
        assert score["invalid_citations"] == 1

    def test_unanswerable_refusal_scores_one(self):
        score = spi_score("The sources do not cover this.", 2, answerable=False)
        assert score["spi"] == 1.0
        assert score["refused"]

    def test_unanswerable_hallucination_scores_zero(self):
        score = spi_score("The budget is 5 million euros [1].", 2, answerable=False)
        assert score["spi"] == 0.0

    def test_refusing_an_answerable_question_scores_zero(self):
        score = spi_score("The sources do not cover this.", 2, answerable=True)
        assert score["spi"] == 0.0

    def test_empty_answer_scores_zero(self):
        assert spi_score("", 2)["spi"] == 0.0


class TestEvaluateGrounded:
    def test_harness_aggregates(self):
        tasks = [
            {"id": "a", "sources": ["s1"], "answerable": True},
            {"id": "b", "sources": ["s1", "s2"], "answerable": False},
        ]

        def answerer(task):
            if task["id"] == "a":
                return "Fact one [1]."
            return "Sources do not cover this."

        result = evaluate_grounded(tasks, answerer)
        assert result["spi"] == 1.0
        assert result["n"] == 2

    def test_perfect_oracle_answerer_scores_one_on_real_suite(self):
        """The shipped suite itself must be winnable — a harness sanity check
        (Calyx lesson: harness bugs fake fitness)."""
        tasks = load_grounded_tasks()
        assert len(tasks) >= 6

        def oracle(task):
            if not task.get("answerable", True):
                return "The sources do not cover this."
            return "Grounded claim [1]."

        result = evaluate_grounded(tasks, oracle)
        assert result["spi"] == 1.0

    def test_ungrounded_answerer_scores_zero_on_real_suite(self):
        tasks = load_grounded_tasks()

        def hallucinator(task):
            return "Here is a confident answer with no citations whatsoever."

        result = evaluate_grounded(tasks, hallucinator)
        assert result["spi"] == 0.0


class TestManifest:
    def test_manifest_covers_grounded_suite(self):
        text = MANIFEST_FILE.read_text(encoding="utf-8")
        assert "grounded.jsonl" in text
        assert "tasks.jsonl" in text

    def test_manifest_verifies(self):
        ok, _ = verify_manifest()
        assert ok

    def test_tampering_is_detected(self, tmp_path):
        # Copy the suite, tamper with the copy, verify against a manifest
        # pointing at it.
        import shutil

        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        shutil.copy(GROUNDED_FILE.parent / "tasks.jsonl", eval_dir / "tasks.jsonl")
        shutil.copy(GROUNDED_FILE, eval_dir / "grounded.jsonl")
        from scribe.evolve.evaluate import write_manifest

        manifest = eval_dir / "MANIFEST.sha256"
        write_manifest(eval_dir / "tasks.jsonl", manifest)
        ok, _ = verify_manifest(eval_dir / "tasks.jsonl", manifest)
        assert ok
        (eval_dir / "grounded.jsonl").write_text('{"id": "evil"}\n')
        ok, detail = verify_manifest(eval_dir / "tasks.jsonl", manifest)
        assert not ok
        assert "grounded" in detail
