# Changelog

All notable changes to Scribe are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
