# Changelog

All notable changes to Scribe are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Multi-model grounding leaderboard.** `scribe-llm bench --models` runs the
  deterministic SPI grounding suite across every model listed in a new
  `["scribe.bench"]` config section (local llama.cpp servers and/or
  OpenAI-compatible endpoints) and writes a reproducible, ranked leaderboard to
  `docs/leaderboard.md` and `docs/leaderboard.json` (with the suite checksum).
  Turns the "answers cite sources or say they can't" claim into a number you can
  compare across backends. The ranking core (`scribe/evolve/leaderboard.py`) is a
  pure, injectable function, tested offline with no server.

## [1.2.0] - 2026-06-19

Major security hardening of the Web SPA interface, sandboxed PTY terminal execution, dynamic PIN setup, and Python 3.12 compatibility fixes.

### Added
- **Interactive Web PIN Setup**: Prompt user to define a custom 4-digit PIN on first start of `scribe-llm web` if not configured in `config.toml`, falling back to generating a secure random 4-digit PIN if non-interactive.
- **Sandboxed PTY Terminal**: Run the integrated web terminal inside a secure, network-isolated `bwrap` (Bubblewrap) container when available, with root filesystem mounted read-only and only the workspace mounted read-write.
- **Rate-limited Login**: Limit Web login attempts to a maximum of 5 attempts within 5 minutes per client IP to prevent brute-forcing.
- **Security Headers & CSWSH Protection**: Restrict WebSocket connections to matching origins only, shorten auth cookie life to 24 hours, and append secure HTTP headers (CSP, X-Frame-Options, X-Content-Type-Options, etc.).
- **Security Logging**: Real-time logging of authentication events, blocked requests, and terminal session life-cycle.

### Fixed
- **preexec_fn Deprecation**: Resolved Python 3.12+ `preexec_fn` deprecation warnings in sandbox execution, using `process_group=0` for process group confinement on Python 3.11+.
- **Legacy Tool Routing**: Routed the legacy `bash()` utility through the sandbox command gate to prevent destructive host operations.


A Crush-inspired makeover of the full-screen `--textual` TUI, plus a small
security touch for the classic TUI.

### Added
- **`charm` theme** (hot-pink primary, electric-purple secondary, mint) and a
  `gradient_text()` helper for Crush-style primary→secondary gradients.
- **Crush-like `--textual` UI**: a gradient `✶ SCRIBE` wordmark in the header,
  `▌ You` / `✦ Scribe` role headers on messages.
- **Models modal (Ctrl+L)** to switch backend (local llama.cpp or any
  OpenAI-compatible API) with a **masked API-key field**; a blank key falls
  back to local or the `SCRIBE_API_KEY` env var.
- **Sessions modal (Ctrl+S)** listing recent sessions (`id · topic · turns`);
  selecting one reloads its transcript.
- **Command palette (Ctrl+P)** with Scribe commands: model backend, resume
  session, toggle code mode, clear chat, quit, and a `Theme → <name>` entry per
  theme.

### Changed
- **Classic TUI masks the API key.** `/models api` now reads the key with a
  hidden (password) prompt, matching the web modal — it no longer shows on
  screen or in scrollback.

## [1.0.0] - 2026-06-18

First stable release. Builds on 0.9.0 with a responsive web layout, reliable
resource grounding, and full Open Knowledge Format conformance.

### Added
- **Responsive web layout.** At ~2/3 width the document-toolbar pills collapse
  to icons (Preview, Raw MD, Lock, History, Export); at ~1/3 width the three
  panes restack vertically — options on top, the document in the middle, the
  chat at the bottom — and the file Explorer becomes an on-demand overlay
  toggled from the activity bar.
- **Grounded answers from resources.** A new **📚 Sources** button answers a
  question strictly from the ingested resources (PDF/TXT/MD/EPUB) with inline
  `[n]` citations, using the proven isolated-grounding path (same as
  `rag ask`). Works without an open document.
- **Best-effort grounding during chat/writing.** Regular turns also retrieve
  relevant resource passages and surface a grounding indicator, when resources
  are present.

### Changed
- **Open Knowledge Format conformance (OKF v0.1).** Wiki pages now carry the
  `resource` URI field (`scribe://session/<id>`) alongside `source`; the index
  uses **bundle-relative links** (`/pages/<file>.md`); and pages end with a
  `# Citations` section. `index.md`/`log.md` reserved files and the required
  `type` field were already in place.
- **Accent recoloring.** The “Apply to Editor” button, tool-call / grounding
  cards, and the Auto-write checkbox now use the pale turquoise-green accent
  (matching the Enter button) instead of blue.

## [0.9.0] - 2026-06-18

A web-editor focused release: the chat and the document are now clearly
separated, with resources, locking and version history added around the
writing surface.

### Added
- **Resources / ingest panel** in the web Explorer. Drop or pick **PDF, TXT,
  MD or EPUB** files; they are saved under `<workspace>/resources/`, indexed
  into RAG as source material, and listed with an `ingest` tag. EPUB text is
  now extracted (stdlib ZIP + XHTML parsing, no new dependency).
- **Lock / protect text.** A `🔒 Lock ▾` menu in the document toolbar locks the
  current **selection** or the **whole page**. Locked regions are fenced with
  `⟦LOCK⟧…⟦/LOCK⟧` sentinels: the model is instructed to reproduce them
  verbatim, manual edits inside them are reverted, and the sentinels are
  stripped from MD/EPUB/PDF exports. Locked spans are highlighted in Preview.
- **Version history.** An `⏱ History ▾` menu lists timestamped snapshots and
  restores any of them. Snapshots are taken on **Save version**, automatically
  **before each model edit**, and (reversibly) **before a restore**. Stored as
  JSON under `documents/<id>/history/`. New REST endpoints:
  `POST /api/docs/{id}/snapshot`, `GET /api/docs/{id}/history`,
  `GET /api/docs/{id}/history/{ts}`, `POST /api/docs/{id}/history/{ts}/restore`.
- **Exit sequence in the web UI** matching the TUI: `Ctrl+Shift+C` arms, then
  `Ctrl+Shift+D` opens a confirmation; confirming signs out and shows a
  goodbye screen (`Esc` cancels).

### Changed
- **Chat no longer prints the document.** When Scribe writes content, the
  conversation pane shows only a small **🪶 writing-into-the-document card**
  (with a live word count); the body itself streams token-by-token into the
  centre page. Text outside `<doc_content>` still appears as normal chat.
- **Follow-the-pen pagination.** While the model writes, the centre pane flips
  to the page currently being written; an exact reflow runs once streaming
  finishes.
- **Richer "magic" quill animation** (gradient feather, glowing nib, an
  ink line that draws itself, and sparkles) replaces the previous flat quill,
  reused in both the typing indicator and the writing card.

## [0.8.0] - 2026-06-17

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

[Unreleased]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.6.0...v0.7.0
[0.2.1]: https://github.com/pedjaurosevic/scribe-llm/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/pedjaurosevic/scribe-llm/releases/tag/v0.2.0
