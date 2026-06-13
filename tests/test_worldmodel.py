"""Tests for the WorldModel persona layer and pulse/diary continuity."""

from __future__ import annotations

import json

from scribe.config import ScribeConfig
from scribe.prompts import get_system_prompt
from scribe.pulse import beat, last_beat, write_diary
from scribe.worldmodel import (
    WorldModel,
    load_worldmodel,
    remember,
    save_worldmodel,
)


class TestWorldModelRender:
    def test_render_is_never_empty(self):
        # Even a blank-ish model renders its identity — no persona-less path.
        wm = WorldModel(identity="I am Scribe.", drives=[], knowledge=[])
        rendered = wm.render()
        assert "I am Scribe." in rendered
        assert rendered.strip()

    def test_render_includes_all_facets(self):
        wm = WorldModel(
            identity="I am Scribe.",
            environment={"host": "po-master", "model": "gemma"},
            knowledge=["The user prefers Serbian."],
            drives=["Cite sources."],
        )
        out = wm.render()
        assert "po-master" in out
        assert "gemma" in out
        assert "prefers Serbian" in out
        assert "Cite sources." in out

    def test_default_drives_present(self):
        assert any("source" in d.lower() for d in WorldModel().drives)


class TestWorldModelPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "wm.json"
        wm = WorldModel(identity="custom", knowledge=["a"])
        save_worldmodel(wm, path)
        loaded = load_worldmodel(path)
        assert loaded.identity == "custom"
        assert loaded.knowledge == ["a"]
        assert loaded.revision == 1

    def test_save_bumps_revision(self, tmp_path):
        path = tmp_path / "wm.json"
        wm = WorldModel()
        save_worldmodel(wm, path)
        save_worldmodel(wm, path)
        assert load_worldmodel(path).revision == 2

    def test_load_missing_returns_seed(self, tmp_path):
        wm = load_worldmodel(tmp_path / "absent.json")
        assert isinstance(wm, WorldModel)
        assert wm.render().strip()

    def test_load_corrupt_returns_seed(self, tmp_path):
        path = tmp_path / "wm.json"
        path.write_text("{ broken json")
        wm = load_worldmodel(path)
        assert wm.identity == WorldModel().identity

    def test_unknown_keys_ignored(self, tmp_path):
        path = tmp_path / "wm.json"
        path.write_text(json.dumps({"identity": "x", "bogus": 1}))
        wm = load_worldmodel(path)
        assert wm.identity == "x"

    def test_remember_dedupes(self, tmp_path):
        path = tmp_path / "wm.json"
        remember("Fact one.", path)
        remember("Fact one.", path)
        remember("Fact two.", path)
        assert load_worldmodel(path).knowledge == ["Fact one.", "Fact two."]


class TestPromptInjection:
    def test_worldmodel_prepended_to_prompt(self):
        wm = WorldModel(identity="I am Scribe, sentinel of port 18083.")
        prompt = get_system_prompt(reasoning=False, worldmodel=wm)
        assert "sentinel of port 18083" in prompt
        # The persona comes first, before the behavioural prompt.
        assert prompt.index("sentinel") < prompt.index("Scribe, an autonomous")

    def test_no_worldmodel_still_works(self):
        prompt = get_system_prompt(reasoning=False)
        assert "Scribe" in prompt

    def test_auto_reasoning_treated_as_on(self):
        # "auto" must not fall through to the no-think prompt.
        prompt = get_system_prompt(reasoning="auto")
        assert "<think>" in prompt


class TestPulse:
    def _config(self):
        return ScribeConfig()

    def test_beat_records_event(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scribe.llm_adapter.LLMAdapter.is_healthy", lambda self: False
        )
        path = tmp_path / "pulse.jsonl"
        event = beat(self._config(), path)
        assert "ts" in event
        assert event["server_up"] is False
        assert last_beat(path)["ts"] == event["ts"]

    def test_last_beat_missing(self, tmp_path):
        assert last_beat(tmp_path / "absent.jsonl") is None

    def test_multiple_beats_append(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scribe.llm_adapter.LLMAdapter.is_healthy", lambda self: False
        )
        path = tmp_path / "pulse.jsonl"
        beat(self._config(), path)
        beat(self._config(), path)
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 2


class TestDiary:
    def test_no_sessions_writes_nothing(self, tmp_path):
        cfg = ScribeConfig()
        cfg.set("scribe", "workspace_dir", str(tmp_path / "empty-ws"))
        assert write_diary(cfg, diary_dir=tmp_path / "diary") is None
