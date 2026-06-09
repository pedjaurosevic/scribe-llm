# Scribe

> Universal TUI agent that connects to **any** llama.cpp server and uses RAG + semantic memory to research, write, and remember — across sessions.

## Features

- **Universal LLM Adapter** — Connect to any llama-server endpoint (local or remote)
- **Rich TUI** — Beautiful terminal interface with progress bars, spinners, and Gruvbox theme
- **Cross-Session Memory** — SME (Semantic Memory Engine) for seamless session continuity
- **RAG Integration** — Semantic search over your document library
- **Modular Skills** — Extend capabilities with skill modules
- **Wittgenstein + Peirce** — Philosophy-inspired harness design for stable LLM behavior

## Installation

```bash
# Clone the repository
git clone https://github.com/pedjaurosevic/scribe-ai.git
cd scribe-ai

# Run install script
./scripts/install.sh

# Or install via pip
pip install -e .
```

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
base_url = "http://127.0.0.1:18083/v1"
model = "your-model.gguf"
```

Or use environment variables:

```bash
export SCRIBE_BASE_URL=http://localhost:18083/v1
export SCRIBE_MODEL=my-model.gguf
```

## CLI Commands

```bash
scribe chat                    # Interactive chat
scribe chat --stream           # Streaming mode (default)

scribe memory recall "query"  # Recall from semantic memory
scribe session last           # Show last session
scribe session list           # List all sessions

scribe config show            # Show current config
scribe status                 # Check system status
```

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
