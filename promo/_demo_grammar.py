#!/usr/bin/env python3
"""
Demo helper for record-demo.sh, scene 1.

Shows the GBNF tool-call grammar in action: a fragment of the generated
grammar, then a real grammar-constrained call to the server, then proof the
result validates. Kept short and colourful for the screencast.
"""

from __future__ import annotations

from scribe.config import ScribeConfig
from scribe.grammar import tool_call_grammar, validate_tool_call
from scribe.llm_adapter import LLMAdapter
from scribe.tools import fs

CYAN, GREEN, DIM, RESET = "\033[0;36m", "\033[1;32m", "\033[2m", "\033[0m"


def main() -> int:
    # The agent has decided the next action is a write; we force EXACTLY that
    # tool, so the only freedom left to the model is to fill valid arguments.
    tools = [t for t in fs.TOOL_SCHEMAS if t["function"]["name"] == "write_file"]
    grammar = tool_call_grammar(tools)

    print(f"{DIM}# GBNF generated from the write_file schema (excerpt):{RESET}")
    for line in grammar.splitlines():
        if line.startswith(("root ", "call-write-file", "args-write-file")):
            print(f"{CYAN}{line[:88]}{RESET}")
    print()

    adapter = LLMAdapter.from_config(ScribeConfig())
    if not adapter.grammar_supported():
        print(f"{DIM}(server is not llama.cpp — grammar enforcement unavailable){RESET}")
        return 0

    prompt = "Save the note 'zdravo svete' to a file called pozdrav.md"
    print(f"{DIM}# asking, constrained by the grammar:{RESET} {prompt}")
    calls = adapter.forced_tool_call(
        [{"role": "user", "content": prompt}], tools, max_tokens=200
    )
    call = calls[0]
    print(f"\n  tool : {GREEN}{call['name']}{RESET}")
    print(f"  args : {call['arguments']}")

    err = validate_tool_call(call, tools)
    verdict = (
        f"{GREEN}VALID — required args present, types correct{RESET}"
        if err is None
        else f"INVALID: {err}"
    )
    print(f"\n  → {verdict}")
    print(f"{DIM}  A malformed call was never possible: the grammar forbids it.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
