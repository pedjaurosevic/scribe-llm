# Changelog

All notable changes to Scribe are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`You` header in `scribe chat`.** Each user turn in the TUI now prints a
  `▌ You` title above the message bubble, mirroring Scribe's own `▌ Scribe`
  header (the web chat already labels turns `You` / `✦ Scribe`).

### Changed
- **Web editor: two view modes + Export menu.** The document toolbar now shows
  just **Preview** (rendered) and **Raw MD** (markdown source); the file export
  formats (Markdown, HTML, EPUB, PDF) moved into an **Export ▾** dropdown. The
  standalone raw-HTML-source view was removed.
- **Web status bar** recolored from VSCode blue to the turquoise-green accent
  used by the Write button.
- **Streaming indicator** is now an animated **quill pen writing lines** instead
  of the waddling cat.

## [0.7.0] - 2026-06-17

### Added
- **Agent system manual seed** (`scribe/seed/system.md`): a single source of
  truth for Scribe's identity and interface model — the writing/research
  copartner persona, the Scribe Chat vs Scribe Web architecture, the
  `<doc_content>` formatting protocol and page-split rules. `prompts.py` now
  loads it (`load_system_md`) as a layer between the constitution and the task
  prompt via `_with_constitution`.
- **Previous-session recall in chat and web.** Both the TUI (`tui.py`) and the
  web WebSocket chat (`web.py`) inject a summary of the user's previous session
  (`recall_previous_session`) into the system prompt, so Scribe can answer
  questions about what was done last time. The home page also receives the
  summary.
- **Session transcripts documented in the prompt.** The system prompt now tells
  Scribe where past sessions live (`sessions/…`) and how the user resumes them
  (`scribe-llm chat resume [TAG]`).

### Changed
- **Web Book Studio editor overhaul** (`editor.html`): A4-style floating pages
  with automatic pagination (chevron nav + `Page X of Y`), Editor / Preview /
  HTML view modes, refined typography (Ubuntu Mono / Courier Prime), Apple-thin
  hover scrollbars, and a streaming "thinking" cat animation.
- **Document writing protocol.** When the model should write into the document
  it wraps the body in `<doc_content>…</doc_content>`; otherwise it replies in
  the chatbox to discuss or confirm (`_compose_writing_prompt`).
- **English-only UI strings.** Remaining Serbian strings in the web export flow
  and print view (`print.html`) are translated to English for the public build.

## [0.6.0] - 2026-06-16

### Added
- **Workspace file explorer in Scribe Web.** The left pane now shows a real
  VSCode-style file tree of `~/scribe-workspace`: folders expand lazily, a
  click opens a file in the middle editor, and edits auto-save back. New
  endpoints `GET /api/files`, `GET /api/file`, `PUT /api/file`, all confined
  to the workspace through `fs._safe_path` (path traversal is rejected). The
  Documents / Books section is kept below the tree.
- **Model backend switcher in Scribe Web** (`⚙` in the top bar). Choose a
  local **llama.cpp** server or any **OpenAI-compatible API** (base URL, model,
  API key) from a modal; `GET`/`POST /api/backend` persist the choice and
  rebuild the adapter live — the web mirror of the TUI `/models` command.

### Changed
- **Softer accent color.** The intense greens (`#4ec9b0`, `#50fa7b`) are
  replaced by a soft pale turquoise-green (`#8fd1c0`) across the editor and
  chat UIs — accent, buttons, status dot, terminal cursor and gutters.
- The web chat can now write into an open workspace file, not only documents.

## [0.5.0] - 2026-06-16

### Added
- **`/models` command in the chat TUI.** Switch the model backend without
  restarting: pick a local **llama.cpp** server (GBNF tool grammar, no API
  key) or any **OpenAI-compatible API** (OpenRouter, Groq, DeepSeek, ...) by
  entering a base URL, model id and API key. The choice is saved to the user
  config and the adapter is rebuilt live. Supports `/models`, `/models local`
  and `/models api`.

### Changed
- **Clearer command help.** `/help` now renders command names in the accent
  color with dimmed, aligned explanations, and the welcome banner hints at
  `/help` and `/models`.

## [0.4.2] - 2026-06-16

### Added
- **PDF ingestion for RAG** (`pypdf`): `scribe-llm rag` can now extract text from
  `.pdf` files. Added `pypdf` to the dependencies.

### Fixed
- **`scribe-llm --version` now reports the real version.** `__version__` is read
  from the installed distribution metadata (`scribe-llm`) instead of a
  hard-coded string that had drifted to `0.3.0`.
- **Robust RAG chunking** (`memory/rag.py`): oversized paragraphs are split
  recursively (by line, then by word) so no chunk can exceed the size limit.

## [0.4.1] - 2026-06-16

### Fixed
- **`scribe-llm web` now runs on native Windows.** The integrated terminal's
  POSIX-only imports (`pty`/`termios`/`fcntl`) were unconditional, so
  `import scribe.web` crashed on Windows. They are now guarded; the terminal
  degrades gracefully where no PTY is available, while the editor, chat and
  book export work on Linux, macOS, Windows and WSL.

### Changed
- **Removed Peirce semiotics from the system prompts.** Reasoning (still
  opt-in; off by default) is now plain step-by-step thinking inside a `<think>`
  block instead of a labelled semiotic chain. "Language games" are kept as
  fixed command meanings.
- README and landing page document Book Studio, the Open Knowledge Format,
  macOS support, the terminal's platform requirements, and the `--host` flag.

## [0.4.0] - 2026-06-16

A web release: a studio for writing books with your local model, and an open
format for the knowledge Scribe distills.

### Added
- **Web Book Studio** (`scribe/templates/editor.html`, `scribe/documents.py`):
  a dark, VSCode/Antigravity-style web UI with three resizable panes
  (Explorer · Editor · Assistant). Books are a table of contents plus one
  markdown file per chapter; the model drafts a TOC, then writes chapter by
  chapter straight into the page. Exports to Markdown, EPUB (pandoc, one
  section per chapter + title page) and PDF (browser print view).
- **Integrated terminal** (`/ws/terminal`): a real login shell in a PTY bridged
  to xterm.js, toggled with `Ctrl+\``, PIN-gated like the rest of the UI.
- **Open Knowledge Format wiki**: `scribe-llm wiki distill` now stores pages as OKF
  markdown — YAML frontmatter (`type/title/description/tags/timestamp/source`),
  `index.md` + `log.md`, inter-page links. `ensure_frontmatter` backfills a
  valid block when the model omits one. SME/RAG are framed as derived indexes
  over these files. See `docs/open-knowledge-format.md`.

### Changed
- The web UI now binds to **`127.0.0.1`** by default (was `0.0.0.0`); the
  integrated shell terminal should not be network-reachable without an explicit
  `--host 0.0.0.0` (which prints a warning).
- PyPI distribution renamed `scribeai` → **`scribe-llm`** (import package and
  CLI remain `scribe`).

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
- **SPI grounding metric** (`scribe/evolve/spi.py`) and **`scribe-llm bench`**:
  deterministic Source-Presence Index over a checksum-locked grounded suite.
- **ORORO traces** (`scribe/trace.py`): append-only canonical-JSON event log
  per session; `scribe-llm trace`.
- **Status contract** (`scribe/status.py`): machine-readable `scribe-llm status --json`.
- **Project vaults** (`scribe/vault.py`): `scribe-llm init` for isolated per-project
  RAG/SME stores.
- **WorldModel** (`scribe/worldmodel.py`): a persona always injected into the
  system prompt; `scribe-llm remember`.
- **Pulse & Diary** (`scribe/pulse.py`): heartbeat log and nightly reflection.
- **Model discovery & blind compare** (`scribe/discovery.py`, `scribe/compare.py`):
  `scribe-llm discover` and `scribe-llm compare`.

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
- FastAPI web UI (`scribe-llm web`).
- Cross-session memory via the Semantic Memory Engine (SME).
- RAG over a local document library (multilingual-e5 embeddings + LanceDB).
- Modular skills: deep-research, writer, wiki-memory.
- Sandboxed workspace file tools (read / write / list, scoped to the workspace).
- Email bridge: send notifications and accept commands from one approved
  address, using only the Python standard library.
- Held-out fitness suite (`scribe-llm evolve eval`).

[Unreleased]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/pedjaurosevic/scribe-llm/releases/tag/v0.2.0
