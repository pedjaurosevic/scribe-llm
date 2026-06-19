"""Tests for the AFK task queue (file-backed, injected executor, no model)."""

from __future__ import annotations

from scribe.queue import DONE, FAILED, PENDING, TaskQueue


def test_add_and_list(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    q.add("summarize the inbox")
    q.add("draft chapter 2")
    tasks = q.list()
    assert [t.prompt for t in tasks] == ["summarize the inbox", "draft chapter 2"]
    assert tasks[0].id == "t001" and tasks[1].id == "t002"
    assert all(t.status == PENDING for t in tasks)


def test_run_next_records_result_and_is_fifo(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    q.add("first")
    q.add("second")
    done = q.run_next(lambda prompt: f"did: {prompt}")
    assert done.prompt == "first"  # oldest pending first
    assert done.status == DONE and done.result == "did: first"
    assert done.finished_at
    # The second task is still pending.
    assert [t.status for t in q.list()] == [DONE, PENDING]


def test_failing_executor_marks_failed_not_crash(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    q.add("boom")

    def explode(_):
        raise RuntimeError("model unavailable")

    done = q.run_next(explode)
    assert done.status == FAILED
    assert "model unavailable" in done.error


def test_run_all_drains_the_queue(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    for i in range(3):
        q.add(f"task {i}")
    finished = q.run_all(lambda p: p.upper())
    assert len(finished) == 3
    assert q.list(PENDING) == []
    assert finished[2].result == "TASK 2"


def test_run_next_on_empty_returns_none(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    assert q.run_next(lambda p: p) is None


def test_clear_by_status(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    q.add("keep me")
    q.add("done me")
    q.run_next(lambda p: "ok")  # marks the first DONE
    removed = q.clear(status=DONE)
    assert removed == 1
    assert [t.status for t in q.list()] == [PENDING]


def test_clear_all(tmp_path):
    q = TaskQueue(tmp_path / "q.json")
    q.add("a")
    q.add("b")
    assert q.clear() == 2
    assert q.list() == []
