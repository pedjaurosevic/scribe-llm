"""Tests for model discovery and blind compare."""

from __future__ import annotations

import random

import pytest

from scribe.compare import BlindComparison, Contestant, build_blind
from scribe.discovery import DEFAULT_PORTS, Endpoint, discover


class TestEndpoint:
    def test_base_url(self):
        ep = Endpoint("127.0.0.1", 18083, ["gemma"])
        assert ep.base_url == "http://127.0.0.1:18083/v1"


class TestDiscover:
    def test_finds_reachable_endpoints(self, monkeypatch):
        def fake_probe(host, port, timeout):
            if port == 18083:
                return Endpoint(host, port, ["gemma-4-12B"])
            return None

        monkeypatch.setattr("scribe.discovery._probe", fake_probe)
        found = discover(hosts=["127.0.0.1"], ports=(18083, 8000))
        assert len(found) == 1
        assert found[0].port == 18083

    def test_localhost_sorted_first(self, monkeypatch):
        def fake_probe(host, port, timeout):
            return Endpoint(host, port, ["m"])

        monkeypatch.setattr("scribe.discovery._probe", fake_probe)
        found = discover(hosts=["100.64.0.5", "127.0.0.1"], ports=(18083,))
        assert found[0].host == "127.0.0.1"

    def test_no_servers(self, monkeypatch):
        monkeypatch.setattr("scribe.discovery._probe", lambda h, p, t: None)
        assert discover(ports=(18083,)) == []

    def test_default_ports_include_common_servers(self):
        # llama.cpp/Scribe, vLLM, LM Studio, Ollama must all be covered.
        for port in (18083, 8000, 1234, 11434):
            assert port in DEFAULT_PORTS


class TestBlindCompare:
    def test_slots_are_shuffled_deterministically_with_seed(self):
        left = Contestant("model-x", "answer x")
        right = Contestant("model-y", "answer y")
        # A fixed seed gives a fixed assignment; both models always present.
        blind = build_blind("q", left, right, rng=random.Random(1))
        assert set(blind.labels()) == {"A", "B"}
        models = {blind.slots["A"].model, blind.slots["B"].model}
        assert models == {"model-x", "model-y"}

    def test_reveal_names_winner_and_loser(self):
        left = Contestant("model-x", "ax")
        right = Contestant("model-y", "ay")
        blind = build_blind("q", left, right, rng=random.Random(0))
        winning_label = "A"
        result = blind.reveal(winning_label)
        assert result["winner"] == blind.slots["A"].model
        assert result["loser"] == blind.slots["B"].model
        assert result["winner"] != result["loser"]

    def test_reveal_tie(self):
        blind = build_blind(
            "q", Contestant("x", "a"), Contestant("y", "b"), rng=random.Random(0)
        )
        result = blind.reveal(None)
        assert result["winner"] is None
        assert result["vote"] is None

    def test_answers_stay_with_their_model(self):
        left = Contestant("x", "answer-from-x")
        right = Contestant("y", "answer-from-y")
        blind = build_blind("q", left, right, rng=random.Random(3))
        for label in ("A", "B"):
            c = blind.slots[label]
            expected = "answer-from-x" if c.model == "x" else "answer-from-y"
            assert c.answer == expected

    def test_shuffle_actually_varies(self):
        # Across many seeds, both orderings should occur.
        left = Contestant("x", "a")
        right = Contestant("y", "b")
        firsts = {
            build_blind("q", left, right, rng=random.Random(s)).slots["A"].model
            for s in range(20)
        }
        assert firsts == {"x", "y"}
