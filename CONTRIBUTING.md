# Contributing to Scribe

Thanks for your interest in improving Scribe. This is a small, focused project —
the aim is a simple, dependable local-LLM agent, not a heavy framework.

## Development setup

```bash
git clone https://github.com/pedjaurosevic/scribe-ai.git
cd scribe-ai
pip install -e ".[dev]"
```

This installs Scribe in editable mode together with the dev tools
(`pytest`, `ruff`, `mypy`).

## Running the checks

```bash
ruff check scribe tests     # lint
pytest -q                   # test suite (no live LLM server required)
```

The test suite is self-contained: tests that need the Semantic Memory Engine
or RAG skip themselves when those optional components aren't available, and
nothing reaches out to a running llama-server. CI runs the same two commands
on Python 3.10, 3.11 and 3.12.

## Pull requests

- Keep changes small and focused; one logical change per PR.
- Run `ruff check` and `pytest` before pushing — CI runs both.
- Use English for code, identifiers, comments and commit messages.
- Update `CHANGELOG.md` under `## [Unreleased]` when you add or change behavior.

## Project layout

```
scribe/
  cli.py            # Click entry point (the `scribe` command)
  session.py        # session manager / cross-session continuity
  llm_adapter.py    # OpenAI-compatible adapter for llama.cpp
  memory/           # SME (semantic memory) + RAG
  tools/            # sandboxed fs + shell tools
  skills/           # modular skill loaders
  ui/               # Rich theme, console, progress, logo
  web.py            # FastAPI web UI
  mail.py           # stdlib-only email bridge
  evolve/           # held-out fitness evaluation
tests/              # pytest suite
docs/               # GitHub Pages landing page
```

## License

By contributing you agree that your contributions are licensed under the MIT
License, the same as the rest of the project.
