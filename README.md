# Scribe

🌐 English · [简体中文](README.zh-CN.md)

[![CI](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Local-first chat + research + coding agent. Connects to **any** OpenAI-compatible server (llama.cpp, Ollama, LM Studio, or a cloud API key) and uses web search, RAG and semantic memory to research, write, and remember — across sessions. Runs comfortably on a 12 GB VRAM machine with Gemma 4 12B at 128k context.

## Why Scribe

Three properties that hold by construction, not by prompt-tuning:

1. **The tool call cannot break.** On a llama.cpp server Scribe enforces tool
   calls with a GBNF grammar generated from the tool schemas — a malformed
   call is *grammatically impossible*, and a model that fumbles is re-asked
   under the grammar. ([scribe/grammar.py](scribe/grammar.py))
2. **Answers cite their sources, or say they can't.** Grounded Q&A maps every
   claim to a numbered source `[n]`, tags `[CONTRADICTION]` when sources
   disagree, and refuses to answer outside the sources. ([scribe/prompts.py](scribe/prompts.py))
3. **Grounding is measured, not asserted.** `scribe bench` reports a
   deterministic Source-Presence Index (SPI) over a checksum-locked held-out
   suite — on Gemma 4 12B it scores **SPI 1.00**. ([scribe/evolve/spi.py](scribe/evolve/spi.py))

> **Honest scope:** GBNF and constrained decoding aren't new — llama.cpp added
> grammars in 2023, and the same idea ships elsewhere as "structured outputs".
> Scribe's contribution is the *integration*: auto-generating the grammar from
> your tool schemas and wiring it as an automatic tool-call safety net for small
> local models. Guarantees 1–3 hold on llama.cpp; other backends degrade to a
> best-effort text parser. The grammar guarantees a call's *form*, not the
> model's *judgment* (it can still pick the wrong tool — it just can't emit a
> malformed one).

📖 Full overview on the [project site](https://pedjaurosevic.github.io/scribe-ai/).

## Features

- **Universal LLM Adapter** — llama.cpp, Ollama, LM Studio, or any OpenAI-compatible cloud API (OpenRouter, Groq, ...) — see [docs/providers.md](docs/providers.md)
- **GBNF Tool Enforcement** — grammar-constrained tool calls on llama.cpp; auto-repair when a model emits a malformed call
- **Grounded Q&A** — hybrid retrieval (FTS5 + vectors, RRF) with mandatory citations and contradiction tagging
- **Quality Gate** — `scribe bench` runs a judge-scored fitness suite and the deterministic SPI grounding metric
- **Safe Code Mode** — `/code` with a destructive-command gate, Python AST gate, bubblewrap sandbox, and git checkpoint/rollback
- **Internet Research** — `web_search` + `web_fetch` tools; DuckDuckGo out of the box, Brave with a key
- **Writing Agent** — deep-research and writer skills for books, papers and reports, with sandboxed workspace file tools
- **Book Studio (web)** — dark, VSCode-style web editor: three resizable panes, an integrated terminal, model-drafted table of contents, chapter-by-chapter writing, and Markdown / EPUB / PDF export
- **Open Knowledge Format** — `scribe wiki distill` curates sessions into portable [OKF](docs/open-knowledge-format.md) markdown (YAML frontmatter + `index.md`/`log.md` + links); SME/RAG are derived indexes over the files
- **Persistent Self** — a WorldModel persona injected into every prompt, plus pulse heartbeat and nightly diary
- **Observability** — ORORO session traces and a machine-readable `scribe status --json` contract
- **Project Vaults** — `scribe init` gives a directory its own isolated RAG/SME stores
- **Model Discovery & Blind Compare** — auto-find local servers; A/B two models without bias
- **Cross-Session Memory** — SME (Semantic Memory Engine) for seamless session continuity
- **Email Bridge** — get results by email and send commands from one approved address (stdlib only)
- **Language games** — explicit command vocabularies (Wittgenstein-inspired) for stable LLM behavior

## Installation

### From PyPI
```bash
pip install scribe-llm       # provides the `scribe` command
```
> The PyPI distribution is named `scribe-llm` (the import package and CLI stay `scribe`).

### From source (🐧 Linux / 🍎 macOS)
```bash
# Clone the repository
git clone https://github.com/pedjaurosevic/scribe-ai.git
cd scribe-ai

# Run the install script: installs the package (editable), creates the
# config, and scaffolds ~/scribe-workspace.
./scripts/install.sh
```

### 🪟 Windows (WSL)
`scribe chat` and the `scribe web` Book Studio run on native Windows too; only
the web UI's **integrated terminal** needs a POSIX PTY (it degrades gracefully
without one). For the full experience, run Scribe via **WSL (Windows Subsystem
for Linux)**.
1. Open your WSL terminal (e.g., Ubuntu).
2. Run the Linux installation commands shown above.
3. To configure Scribe to work with **Ollama** (either running natively on Windows or inside WSL), check out the [WSL & Ollama Integration Guide](docs/wsl_ollama_guide.md).

---

Or install by hand (skip the script):

```bash
pip install -e .
```

> Requires Python 3.10+. The install is editable, so `git pull` updates Scribe in place.

## Quick Start

1. Start your llama-server:
```bash
./scripts/start-server.sh
```

2. Start Scribe:
```bash
scribe chat
```

3. Scribe will automatically recall your last session and ask if you want to continue.

## Configuration

Edit `~/.config/scribe/config.toml`:

```toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"   # llama.cpp / Ollama / LM Studio / cloud
model = "default"                         # auto-detects the loaded model
api_key = "not-needed"                    # set a real key for cloud providers
```

Or use environment variables:

```bash
export SCRIBE_BASE_URL=http://localhost:11434/v1   # e.g. Ollama
export SCRIBE_MODEL=gemma4:12b
export SCRIBE_API_KEY=sk-...                       # cloud providers only
```

**Full provider guide** — llama.cpp, Ollama, LM Studio, OpenRouter/Groq, plus
a recipe for **Gemma 4 12B with 128k context on a 12 GB GPU**:
[docs/providers.md](docs/providers.md).

**Web search** needs no setup (DuckDuckGo). For Brave Search, set
`BRAVE_API_KEY` or `brave_api_key` under `[scribe]`.

## CLI Commands

```bash
scribe chat                    # Interactive TUI chat (streaming by default)
scribe chat --textual          # Full-screen Textual UI (experimental)
scribe chat --resume TAG       # Resume a past session (no TAG = last one)
scribe web                     # Book Studio web UI at http://localhost:8765 (localhost-only by default)
scribe web --host 0.0.0.0      # Expose on the network (prints a warning — the UI has a shell terminal)

scribe memory recall "query"  # Recall from semantic memory
scribe rag search "query"     # Hybrid search (FTS5 + vectors); --semantic-only to opt out
scribe rag ask "question"     # Grounded Q&A — answers cite sources or refuse
scribe rag reindex             # Rebuild the lexical (FTS5) index
scribe session last            # Show last session
scribe session list            # List all sessions
scribe session search "query" # Full-text search across all session transcripts

scribe init [DIR]              # Create a project-local vault (config + ./.scribe)
scribe discover [--tailscale]  # Find OpenAI-compatible model servers
scribe compare "q" --a M1 --b M2  # Blind A/B two models on one prompt
scribe bench [--fitness|--spi] # Quality gate: judge fitness + SPI grounding
scribe trace [ID] [--json]     # Show a session's ORORO trace

scribe pulse                   # Record one heartbeat (wire to a systemd timer)
scribe diary                   # Reflect on today's sessions
scribe remember "fact"        # Add a durable fact to the WorldModel

scribe config show             # Show current config
scribe status [--json]         # System status (--json = machine-readable contract)
scribe evolve eval             # Run the held-out fitness suite (Phase 0)

scribe mail send "Subj" "Body" # Email yourself a notification
scribe mail watch              # Accept commands by email (see below)
```

## Email bridge

Scribe can email you results and accept commands by email — using only the
Python standard library (no extra dependencies).

```toml
[scribe.email]
enabled = true
address = "you@gmail.com"
approved_sender = "you@gmail.com"   # the ONLY address allowed to command Scribe
secret = "pick-a-token"             # must appear in command subjects
```

```bash
export SCRIBE_EMAIL_PASSWORD="your-gmail-app-password"   # never in the config file

scribe mail send "Done" "The report is ready."   # send a notification
scribe mail watch                                 # poll inbox, run commands, reply
```

To run a command, email yourself with the secret in the subject:

> **Subject:** `[scribe:pick-a-token] summarize the notes in research/`

Scribe runs it with the **sandboxed workspace tools** (read/write/list files,
no shell) and replies with the answer.

**Security:** commands are accepted only when both the sender matches
`approved_sender` **and** the subject carries `[scribe:secret]`. Since `From:`
headers can be spoofed, the secret is the real gate — leave it empty to keep
command intake off (sending still works). Gmail requires an
[App Password](https://myaccount.google.com/apppasswords) (with 2-Step
Verification enabled).

## Architecture

```
┌─────────────────────────────────────────┐
│              SCRIBE TUI                  │
│           (Rich-based interface)          │
├─────────────────────────────────────────┤
│              CORE KERNEL                 │
│  Session Manager │ Skills │ Config       │
├─────────────────────────────────────────┤
│           LLM ADAPTER LAYER              │
│    OpenAI-compatible (llama.cpp)         │
├─────────────────────────────────────────┤
│             MEMORY LAYER                 │
│  SME (cross-session) │ RAG (documents)  │
├─────────────────────────────────────────┤
│              TOOLS LAYER                 │
│   web_search │ web_fetch │ bash         │
└─────────────────────────────────────────┘
```

## Philosophy

**Language games (Wittgenstein-inspired).** Each command word has a fixed,
explicit meaning, so the model knows exactly what each action means. Reasoning,
when enabled, stays in a `<think>` block and never leaks into the answer; by
default Scribe answers directly.

## License

MIT
