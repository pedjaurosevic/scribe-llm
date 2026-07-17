"""EVOLVE-SCRIBE Phase 0: eval loading, checksum, scoring (no live model)."""

from scribe.evolve import evaluate as ev


def test_tasks_load_and_count():
    tasks = ev.load_tasks()
    assert len(tasks) == 32
    for t in tasks:
        assert {"id", "lang", "prompt", "max_words", "rubric"} <= set(t)


def test_manifest_matches_shipped_suite():
    ok, _ = ev.verify_manifest()
    assert ok, "held-out suite no longer matches its checksum manifest"


def test_manifest_detects_tampering(tmp_path):
    tasks = tmp_path / "tasks.jsonl"
    manifest = tmp_path / "MANIFEST.sha256"
    tasks.write_text('{"id":"a"}\n', encoding="utf-8")
    ev.write_manifest(tasks, manifest)
    assert ev.verify_manifest(tasks, manifest)[0] is True
    tasks.write_text('{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")  # tamper
    assert ev.verify_manifest(tasks, manifest)[0] is False


def test_parse_judge():
    assert ev.parse_judge('{"score": 9, "language_ok": true}') == (9, True)
    assert ev.parse_judge('blah {"score": 15, "language_ok": false} x') == (10, False)
    assert ev.parse_judge("I would rate this a 7 out of 10") == (7, True)
    assert ev.parse_judge("no number here")[0] == 0


def test_evaluate_aggregates_with_fakes():
    tasks = [
        {"id": "t1", "lang": "sr", "prompt": "x", "max_words": 5, "rubric": "ok"},
        {"id": "t2", "lang": "en", "prompt": "y", "max_words": 2, "rubric": "ok"},
    ]
    # t1: perfect & brief; t2: half score, too long, wrong language
    answers = {"t1": "kratko", "t2": "this answer is way too long for the limit"}
    judges = {"t1": (10, True), "t2": (5, False)}
    res = ev.evaluate(
        tasks,
        answerer=lambda t: answers[t["id"]],
        judge=lambda t, a: judges[t["id"]],
    )
    assert res["n"] == 2
    assert abs(res["fitness"] - 0.75) < 1e-9          # (1.0 + 0.5) / 2
    assert abs(res["lang_ok_rate"] - 0.5) < 1e-9
    assert abs(res["brief_ok_rate"] - 0.5) < 1e-9     # t1 brief, t2 not


def test_constitution_in_system_prompt():
    from scribe.prompts import get_system_prompt, load_constitution
    assert load_constitution()  # non-empty
    prompt = get_system_prompt(reasoning=True)
    assert "Constitution" in prompt
    assert "same language" in prompt.lower()
