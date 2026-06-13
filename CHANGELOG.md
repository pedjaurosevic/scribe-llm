# Changelog

All notable changes to Scribe are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-06-13

A synthesis release: the strongest mechanisms from sibling local-agent
projects (Synap, Konok, ExoLab, CANYON) and Odysseus, folded into Scribe.

### Added
- **GBNF tool-call enforcement** (`scribe/grammar.py`): a grammar generated
  from the tool schemas makes a malformed tool call grammatically impossible
  on llama.cpp; `tool_grammar = "auto"` re-asks a fumbled call under the
  grammar, `"force"` constrains every forced call.
- **Reasoning gate** (`scribe/reasoning_gate.py`): `reasoning = "auto"` enables
  server-side thinking only for prompts that benefit (code, debugging,
  multi-step, long), bilingual EN/SR heuristic.
- **Execution sandbox** (`scribe/tools/sandbox.py`): destructive-command gate,
  Python AST gate, and a bubblewrap container (read-only root, writable
  workspace, no network) with CPU/memory limits; degrades without bwrap.
- **Git checkpoint/rollback** (`scribe/tools/checkpoint.py`): `workspace_checkpoint`
  / `workspace_rollback` tools and a verify-then-roll-back loop; snapshots as
  git tree objects that leave history untouched.
- **Hybrid retrieval** (`scribe/memory/hybrid.py`): SQLite FTS5 lexical branch
  fused with vector search via Reciprocal Rank Fusion. `rag search` is hybrid
  by default; new `rag ask` (grounded Q&A) and `rag reindex`.
- **Citation grounding** (`scribe/prompts.py`): numbered sources, mandatory
  `[n]` citations, `[CONTRADICTION]` tagging, refusal outside the sources.
- **SPI grounding metric** (`scribe/evolve/spi.py`) and **`scribe bench`**:
  deterministic Source-Presence Index over a checksum-locked grounded suite.
- **ORORO traces** (`scribe/trace.py`): append-only canonical-JSON event log
  per session; `scribe trace`.
- **Status contract** (`scribe/status.py`): machine-readable `scribe status --json`.
- **Project vaults** (`scribe/vault.py`): `scribe init` for isolated per-project
  RAG/SME stores.
- **WorldModel** (`scribe/worldmodel.py`): a persona always injected into the
  system prompt; `scribe remember`.
- **Pulse & Diary** (`scribe/pulse.py`): heartbeat log and nightly reflection.
- **Model discovery & blind compare** (`scribe/discovery.py`, `scribe/compare.py`):
  `scribe discover` and `scribe compare`.

### Changed
- `LLMAdapter` gained `thinking_mode` and `tool_grammar`; `_with_thinking`
  is now message-aware for the reasoning gate.
- `verify_manifest` covers multiple held-out suite files.

## [0.2.1] - 2026-06-09

### Added
- GitHub Actions CI: runs `ruff` lint and the unit `pytest` subset
  (`-m "not integration"`) on Python 3.10 / 3.11 / 3.12 for every push and PR.
- `integration` pytest marker for tests that need a live llama-server or model
  downloads, so the unit suite stays fast and runnable anywhere.
- `CONTRIBUTING.md` with the local dev / test workflow.
- Status badges in the README.

### Changed
- Clarified the install steps in the README and landing page: `./scripts/install.sh`
  already installs the package, so the extra `pip install -e .` is now shown only
  as the manual alternative.

### Fixed
- Cleaned up the codebase so `ruff` passes on the full lint rule set
  (import order, unused imports, f-strings, modern type hints) — no behavior change.
- Declared previously-undeclared runtime dependencies that a clean install was
  missing: `textual` (Textual UI import), and `pandas` + `pylance` (required by
  the LanceDB-backed memory layer — without them `list_sources`/search silently
  returned empty results).

## [0.2.0] - 2026-06-08

### Added
- Initial public release.
- Universal LLM adapter for any OpenAI-compatible (llama.cpp) endpoint.
- Rich-based TUI with a streaming chat, plus an experimental Textual full-screen UI.
- FastAPI web UI (`scribe web`).
- Cross-session memory via the Semantic Memory Engine (SME).
- RAG over a local document library (multilingual-e5 embeddings + LanceDB).
- Modular skills: deep-research, writer, wiki-memory.
- Sandboxed workspace file tools (read / write / list, scoped to the workspace).
- Email bridge: send notifications and accept commands from one approved
  address, using only the Python standard library.
- Held-out fitness suite (`scribe evolve eval`).

[Unreleased]: https://github.com/pedjaurosevic/scribe-ai/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/pedjaurosevic/scribe-ai/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/pedjaurosevic/scribe-ai/releases/tag/v0.2.0
