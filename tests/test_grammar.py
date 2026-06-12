"""Tests for GBNF tool-call grammar, validation and the reasoning gate."""

from __future__ import annotations

import re

import pytest

from scribe.grammar import (
    looks_like_tool_call,
    tool_call_grammar,
    validate_tool_call,
)
from scribe.llm_adapter import LLMAdapter
from scribe.reasoning_gate import last_user_text, should_think
from scribe.tools import fs, shell

ALL_TOOLS = fs.TOOL_SCHEMAS + shell.TOOL_SCHEMAS

GBNF_RULE = re.compile(r"^([a-z0-9-]+) ::= ", re.MULTILINE)


class TestToolCallGrammar:
    def test_grammar_has_root_and_one_rule_per_tool(self):
        grammar = tool_call_grammar(ALL_TOOLS)
        rules = GBNF_RULE.findall(grammar)
        assert "root" in rules
        for tool in ALL_TOOLS:
            name = tool["function"]["name"].replace("_", "-")
            assert f"call-{name}" in rules
            assert f"args-{name}" in rules

    def test_tool_names_appear_as_quoted_literals(self):
        grammar = tool_call_grammar(fs.TOOL_SCHEMAS)
        assert '"\\"write_file\\""' in grammar
        assert '"\\"arguments\\""' in grammar

    def test_required_keys_are_forced(self):
        grammar = tool_call_grammar([fs.TOOL_SCHEMAS[0]])  # write_file
        args_rule = next(
            line for line in grammar.splitlines() if line.startswith("args-write-file")
        )
        assert '"\\"path\\""' in args_rule
        assert '"\\"content\\""' in args_rule

    def test_no_required_keys_falls_back_to_generic_object(self):
        list_dir = next(
            t for t in fs.TOOL_SCHEMAS if t["function"]["name"] == "list_dir"
        )
        grammar = tool_call_grammar([list_dir])
        args_rule = next(
            line for line in grammar.splitlines() if line.startswith("args-list-dir")
        )
        assert "object" in args_rule

    def test_every_referenced_rule_is_defined(self):
        grammar = tool_call_grammar(ALL_TOOLS)
        defined = set(GBNF_RULE.findall(grammar))
        # Strip quoted terminals and char classes, then collect identifiers.
        stripped = re.sub(r'"(\\.|[^"\\])*"', " ", grammar)
        stripped = re.sub(r"\[(\\.|[^\]\\])*\]", " ", stripped)
        body = "\n".join(
            line.split("::=", 1)[1] for line in stripped.splitlines() if "::=" in line
        )
        referenced = set(re.findall(r"\b([a-z][a-z0-9-]*)\b", body))
        assert referenced <= defined, referenced - defined

    def test_enum_becomes_literal_alternation(self):
        tool = {
            "type": "function",
            "function": {
                "name": "set_mode",
                "parameters": {
                    "type": "object",
                    "properties": {"mode": {"type": "string", "enum": ["fast", "safe"]}},
                    "required": ["mode"],
                },
            },
        }
        grammar = tool_call_grammar([tool])
        assert '"\\"fast\\"" | "\\"safe\\""' in grammar

    def test_empty_tools_raise(self):
        with pytest.raises(ValueError):
            tool_call_grammar([])


class TestValidateToolCall:
    def test_valid_call_passes(self):
        call = {"name": "write_file", "arguments": '{"path": "a.md", "content": "x"}'}
        assert validate_tool_call(call, fs.TOOL_SCHEMAS) is None

    def test_dict_arguments_accepted(self):
        call = {"name": "read_file", "arguments": {"path": "a.md"}}
        assert validate_tool_call(call, fs.TOOL_SCHEMAS) is None

    def test_unknown_tool_rejected(self):
        call = {"name": "rm_rf", "arguments": "{}"}
        assert "unknown tool" in validate_tool_call(call, fs.TOOL_SCHEMAS)

    def test_broken_json_rejected(self):
        call = {"name": "write_file", "arguments": '{"path": "a.md", "content": '}
        assert "not valid JSON" in validate_tool_call(call, fs.TOOL_SCHEMAS)

    def test_missing_required_rejected(self):
        call = {"name": "write_file", "arguments": '{"path": "a.md"}'}
        assert "content" in validate_tool_call(call, fs.TOOL_SCHEMAS)

    def test_non_object_arguments_rejected(self):
        call = {"name": "run_bash", "arguments": '"ls"'}
        assert "object" in validate_tool_call(call, shell.TOOL_SCHEMAS)


class TestLooksLikeToolCall:
    def test_envelope_keys_detected(self):
        assert looks_like_tool_call('{"name": "write_file", "argum', fs.TOOL_SCHEMAS)

    def test_tool_name_mention_detected(self):
        assert looks_like_tool_call("I will run_bash now", shell.TOOL_SCHEMAS)

    def test_plain_prose_not_detected(self):
        assert not looks_like_tool_call("{just a brace in prose}", fs.TOOL_SCHEMAS)

    def test_empty_not_detected(self):
        assert not looks_like_tool_call("   ", fs.TOOL_SCHEMAS)


class TestReasoningGate:
    @pytest.mark.parametrize("text", ["hi", "hvala!", "ok", "Zdravo", "thanks"])
    def test_small_talk_does_not_think(self, text):
        assert should_think(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "Why does the build fail on python 3.12?",
            "Objasni zašto test pada",
            "Debug this:\n```\nTraceback (most recent call last)\n```",
            "Plan: 1. parse 2. validate 3. emit",
        ],
    )
    def test_complex_requests_think(self, text):
        assert should_think(text) is True

    def test_long_prompt_thinks(self):
        assert should_think("word " * 100) is True

    def test_short_statement_does_not_think(self):
        assert should_think("rename the file to notes.md") is False

    def test_last_user_text_picks_latest_user(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "second"},
        ]
        assert last_user_text(messages) == "second"
        assert last_user_text([]) == ""


class TestAdapterGrammarWiring:
    def _adapter(self, mode="auto"):
        adapter = LLMAdapter(base_url="http://127.0.0.1:9", tool_grammar=mode)
        adapter._grammar_supported = False  # never touch the network in tests
        return adapter

    def test_valid_calls_need_no_repair(self):
        adapter = self._adapter()
        calls = [{"name": "read_file", "arguments": '{"path": "a.md"}'}]
        assert adapter._repair_tool_calls([], fs.TOOL_SCHEMAS, calls, "") is None
        assert adapter.last_tool_repair is None

    def test_off_mode_never_repairs(self):
        adapter = self._adapter(mode="off")
        calls = [{"name": "nope", "arguments": "{}"}]
        assert adapter._repair_tool_calls([], fs.TOOL_SCHEMAS, calls, "") is None

    def test_broken_call_without_grammar_support_passes_through(self):
        adapter = self._adapter()
        calls = [{"name": "write_file", "arguments": "{broken"}]
        assert adapter._repair_tool_calls([], fs.TOOL_SCHEMAS, calls, "") is None

    def test_broken_call_with_grammar_support_repairs(self, monkeypatch):
        adapter = self._adapter()
        adapter._grammar_supported = True
        fixed = [{"name": "write_file", "arguments": '{"path": "a", "content": "b"}'}]
        monkeypatch.setattr(adapter, "forced_tool_call", lambda *a, **k: fixed)
        calls = [{"name": "write_file", "arguments": "{broken"}]
        out = adapter._repair_tool_calls([], fs.TOOL_SCHEMAS, calls, "")
        assert out == fixed
        assert "not valid JSON" in adapter.last_tool_repair

    def test_unparseable_text_blob_repairs(self, monkeypatch):
        adapter = self._adapter()
        adapter._grammar_supported = True
        fixed = [{"name": "list_dir", "arguments": "{}"}]
        monkeypatch.setattr(adapter, "forced_tool_call", lambda *a, **k: fixed)
        blob = '{"name": "list_dir", "arguments": {"path": '  # truncated mid-call
        out = adapter._repair_tool_calls([], fs.TOOL_SCHEMAS, [], blob)
        assert out == fixed

    def test_thinking_mode_auto_uses_gate(self):
        adapter = self._adapter()
        adapter.thinking_mode = "auto"
        kwargs = adapter._with_thinking(
            {}, [{"role": "user", "content": "Why does this crash?"}]
        )
        assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
        kwargs = adapter._with_thinking({}, [{"role": "user", "content": "hi"}])
        assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    def test_thinking_mode_on_off_static(self):
        adapter = self._adapter()
        adapter.thinking_mode = "on"
        kwargs = adapter._with_thinking({}, [{"role": "user", "content": "hi"}])
        assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
        adapter.thinking_mode = "off"
        kwargs = adapter._with_thinking({}, [{"role": "user", "content": "why?"}])
        assert kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
