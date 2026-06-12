"""
GBNF tool-call grammar — the tool call that cannot break.

Builds a llama.cpp GBNF grammar from OpenAI-style tool schemas so that, when
applied, the model is *grammatically unable* to emit a malformed tool call:
the output must be a single JSON object {"name": <known tool>, "arguments":
{...}} whose required arguments are present and correctly typed.

Used two ways by the adapter:
- "force": every tool-decision request carries the grammar.
- "auto" (default): the normal turn runs unconstrained; if the model fumbles
  the tool-call format, the harness retries that single request with the
  grammar attached, making invalid output impossible the second time.

Only llama.cpp servers accept the `grammar` field; support is probed via the
server's /props endpoint and the feature degrades to a no-op elsewhere.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Core JSON rules, adapted from llama.cpp's json.gbnf.
_JSON_RULES = r"""
value ::= object | array | string | number | boolean | null
object ::= "{" ws ( string ws ":" ws value ( ws "," ws string ws ":" ws value )* )? ws "}"
array ::= "[" ws ( value ( ws "," ws value )* )? ws "]"
string ::= "\"" ( [^"\\\x7F\x00-\x1F] | "\\" (["\\bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]) )* "\""
number ::= "-"? ( [0-9] | [1-9] [0-9]* ) ( "." [0-9]+ )? ( [eE] [-+]? [0-9]+ )?
integer ::= "-"? ( [0-9] | [1-9] [0-9]* )
boolean ::= "true" | "false"
null ::= "null"
ws ::= [ \t\n]{0,8}
""".strip()


def _rule_name(text: str) -> str:
    """GBNF rule names allow only [a-z0-9-]; tool names use underscores."""
    name = re.sub(r"[^a-zA-Z0-9-]", "-", text).lower().strip("-")
    return name or "tool"


def _quote(literal: str) -> str:
    """A JSON string literal embedded in a GBNF quoted terminal."""
    inner = json.dumps(literal)[1:-1]          # JSON-escape the content
    escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
    return f'"\\"{escaped}\\""'


def _value_rule(prop_schema: dict[str, Any]) -> str:
    """GBNF rule expression for one argument value, from its JSON schema."""
    enum = prop_schema.get("enum")
    if enum and all(isinstance(v, str) for v in enum):
        return " | ".join(_quote(v) for v in enum)
    return {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "array": "array",
        "object": "object",
    }.get(prop_schema.get("type", ""), "value")


def _args_rule(parameters: dict[str, Any]) -> str:
    """
    Grammar for one tool's arguments object: required properties first, in
    schema order, then the optional ones — each typed from the schema.
    """
    props: dict[str, Any] = parameters.get("properties") or {}
    required = [k for k in parameters.get("required") or [] if k in props]
    optional = [k for k in props if k not in required]

    def pair(key: str) -> str:
        return f'{_quote(key)} ws ":" ws ( {_value_rule(props[key])} )'

    parts: list[str] = []
    for i, key in enumerate(required):
        prefix = '"," ws ' if i else ""
        parts.append(f"{prefix}{pair(key)} ws")
    for key in optional:
        comma = '"," ws ' if required else ""
        # Optional keys after required ones; when nothing is required, fall
        # back to a generic object so the empty-args case stays reachable.
        if required:
            parts.append(f'( {comma}{pair(key)} ws )?')
    if not required:
        return "object"
    return '"{" ws ' + " ".join(parts) + '"}"'


def tool_call_grammar(tools: list[dict[str, Any]]) -> str:
    """
    Build the full GBNF grammar for a set of OpenAI-style tool schemas.

    Root accepts exactly one call object; "name" is an enum of the advertised
    tools and "arguments" must satisfy that tool's parameter schema.
    """
    if not tools:
        raise ValueError("tool_call_grammar needs at least one tool schema")

    call_rules: list[str] = []
    arg_rules: list[str] = []
    names: list[str] = []
    for tool in tools:
        fn = tool.get("function", tool)
        name = fn["name"]
        rule = _rule_name(name)
        names.append(f"call-{rule}")
        arg_rules.append(f"args-{rule} ::= {_args_rule(fn.get('parameters') or {})}")
        call_rules.append(
            f'call-{rule} ::= "{{" ws {_quote("name")} ws ":" ws {_quote(name)} ws '
            f'"," ws {_quote("arguments")} ws ":" ws args-{rule} ws "}}"'
        )

    # No leading ws: the very first sampled token must open the call object,
    # otherwise models that "wanted" to emit prose stall in a whitespace loop.
    lines = [f"root ::= ( {' | '.join(names)} ) ws"]
    lines += call_rules
    lines += arg_rules
    lines.append(_JSON_RULES)
    return "\n".join(lines)


def validate_tool_call(call: dict[str, Any], tools: list[dict[str, Any]]) -> str | None:
    """
    Check one parsed call dict (id/name/arguments) against the advertised
    schemas. Returns an error description, or None when the call is sound.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for tool in tools:
        fn = tool.get("function", tool)
        by_name[fn["name"]] = fn.get("parameters") or {}

    name = call.get("name", "")
    if name not in by_name:
        return f"unknown tool '{name}'"

    raw = call.get("arguments", "{}")
    if isinstance(raw, str):
        try:
            args = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            return f"arguments are not valid JSON: {exc}"
    else:
        args = raw
    if not isinstance(args, dict):
        return "arguments must be a JSON object"

    missing = [k for k in by_name[name].get("required") or [] if k not in args]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    return None


def looks_like_tool_call(text: str, tools: list[dict[str, Any]]) -> bool:
    """
    Heuristic for the repair path: does this unparseable leftover plausibly
    *try* to be a tool call (as opposed to prose that happens to start with a
    brace)? True when it mentions a call envelope key or an advertised tool.
    """
    if not text.strip():
        return False
    sample = text[:2000]
    if '"name"' in sample or '"action"' in sample or '"arguments"' in sample:
        return True
    for tool in tools:
        fn = tool.get("function", tool)
        if fn["name"] in sample:
            return True
    return False
