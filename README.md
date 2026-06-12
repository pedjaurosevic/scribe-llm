# Scribe

🌐 English · [简体中文](README.zh-CN.md)

[![CI](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Local-first chat + research + coding agent. Connects to **any** OpenAI-compatible server (llama.cpp, Ollama, LM Studio, or a cloud API key) and uses web search, RAG and semantic memory to research, write, and remember — across sessions. Runs comfortably on a 12 GB VRAM machine with Gemma 4 12B at 128k context.

## Features

- **Universal LLM Adapter** — llama.cpp, Ollama, LM Studio, or any OpenAI-compatible cloud API (OpenRouter, Groq, ...) — see [docs/providers.md](docs/providers.md)
- **Internet Research** — `web_search` + `web_fetch` tools; works out of the box via DuckDuckGo (no API key), upgrades to Brave Search with a key
- **Writing Agent** — deep-research and writer skills for books, papers and reports on any topic, with sandboxed workspace file tools
- **Coding Mode** — `/code` turns Scribe into a terminal expert with full (per-command confirmed) bash access
- **Rich TUI** — Beautiful terminal interface with streaming, themes, and live reasoning marquee
- **Cross-Session Memory** — SME (Semantic Memory Engine) for seamless session continuity
- **RAG Integration** — Semantic search over your document library
- **Modular Skills** — Extend capabilities with skill modules
- **Email Bridge** — Get results by email and send commands from one approved address (stdlib only)
- **Wittgenstein + Peirce** — Philosophy-inspired harness design for stable LLM behavior

## Installation

### 🐧 Linux
```bash
# Clone the repository
git clone https://github.com/pedjaurosevic/scribe-ai.git
cd scribe-ai

# Run the install script: installs the package (editable), creates the
# config, and scaffolds ~/scribe-workspace.
./scripts/install.sh
```

### 🪟 Windows (WSL)
Scribe runs seamlessly on Windows via **WSL (Windows Subsystem for Linux)**.
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
scribe web                     # Web UI at http://localhost:8765

scribe memory recall "query"  # Recall from semantic memory
scribe rag search "query"     # Semantic search over ingested documents
scribe session last            # Show last session
scribe session list            # List all sessions
scribe session search "query" # Full-text search across all session transcripts

scribe config show             # Show current config
scribe status                  # Check system status
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

Scribe is built on two philosophical pillars:

1. **Wittgenstein** — Language games define meaning. Scribe uses explicit command vocabularies so the model knows exactly what each action means.

2. **Peirce** — Signs gain meaning through interpretation chains. Scribe maintains semiotic continuity: every response becomes the next sign in the chain.

## License

MIT
