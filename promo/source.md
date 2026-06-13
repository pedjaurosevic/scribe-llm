# Scribe — canonical launch text

> Single source for the launch. Every channel (HN, Reddit, dev.to, X, YouTube
> description) is generated/trimmed from this file. Keep it true; trim per
> channel, never embellish.

---

## One-liner

A local-first TUI agent for any OpenAI-compatible server (llama.cpp, Ollama,
LM Studio, cloud) with three guarantees most local agents don't make:
**tool calls that can't break, answers that cite their sources or refuse, and
grounding that is measured — not claimed.**

## Hook (the problem)

Small local models are great until you hand them tools. The tool call comes
back as half-valid JSON, or the model confidently invents a fact and formats
it beautifully. Most agents paper over this with retries and hope. Scribe
removes the hope:

1. **The tool call cannot break.** On llama.cpp, Scribe builds a GBNF grammar
   from your tool schemas, so a malformed call is *grammatically impossible*.
   If a model still fumbles, the call is re-asked under the grammar.
2. **Cite or refuse.** Grounded Q&A maps every claim to a numbered source
   `[n]`, tags `[CONTRADICTION]` when sources disagree, and refuses to answer
   outside the sources instead of hallucinating.
3. **Grounding is measured.** `scribe bench` reports a deterministic
   Source-Presence Index over a checksum-locked held-out suite. On Gemma 4 12B
   it scores SPI 1.00 — and you can re-run it on your own model.

## What it is (plainly)

- ~7k lines of Python, 250+ tests, runs comfortably on a 12 GB VRAM machine.
- TUI chat + research + a `/code` mode with a destructive-command gate, Python
  AST gate, bubblewrap sandbox, and git checkpoint/rollback.
- Hybrid retrieval (FTS5 + vectors, RRF), cross-session semantic memory, a
  persistent WorldModel persona, ORORO session traces, project-local vaults.
- Model discovery and blind A/B compare so you can pick a local model honestly.

## Try it in 2 minutes

```bash
git clone https://github.com/pedjaurosevic/scribe-ai && cd scribe-ai
./scripts/install.sh
scribe discover          # find your local model server
scribe chat              # start talking
scribe bench             # see the grounding number for yourself
```

## Honest limitations (state these, don't hide them)

- Young project, primarily one author. The code is small enough to read in an
  afternoon — that's the point.
- Verified mainly on Gemma 4 12B via llama.cpp; broader model coverage is
  exactly where outside testers help most.
- The shipped SPI suite is small and self-authored — it's a regression gate,
  not independent proof. Re-run it on your own data and tell me what breaks.

---

## Channel variants (generated from the above)

### Show HN title
`Show HN: Scribe – a local AI agent whose tool calls can't break and whose answers cite sources`

### r/LocalLLaMA title
`I built Scribe: a local TUI agent with grammar-enforced tool calls and measured grounding (SPI)`

### dev.to article angle
"How I made local tool-calls unbreakable with GBNF" — walk through grammar.py,
the auto-repair path, and the SPI bench. Code-heavy, honest about tradeoffs.

### X / Bluesky thread (segments)
1. Local models break tool calls and hallucinate. I got tired of hoping. 🧵
2. Scribe builds a GBNF grammar from your tool schemas — a malformed tool call
   becomes grammatically impossible on llama.cpp. [demo gif]
3. Every answer cites its source [n] or refuses. No silent hallucination.
4. And it's measured: `scribe bench` → SPI 1.00 on Gemma 4 12B. Run it yourself.
5. Local-first, ~7k lines, 250+ tests, MIT. github.com/pedjaurosevic/scribe-ai
