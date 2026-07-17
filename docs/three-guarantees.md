# Three Guarantees by Construction

**A short technical note on how Scribe makes an LLM agent's promises
structural instead of rhetorical.**

*Pedja Urosevic · July 2026 · [scribe-llm](https://github.com/pedjaurosevic/scribe-llm)*

---

Most agent frameworks make three promises in the system prompt: *call tools
correctly, don't make things up, trust us*. Scribe's position is that a
promise which lives only in the prompt is a request, not a guarantee. This
note describes three properties that hold **by construction** — enforced by
decoding constraints, prompt isolation, and a locked measurement — and shows
what happens when they are measured across a fleet of models.

## Guarantee 1 — The tool call cannot break

When Scribe needs a tool call and the model fumbles it (broken JSON, unknown
tool, half-emitted blob), it re-asks under a **GBNF grammar generated from
the tool schemas** ([`scribe/grammar.py`](../scribe/grammar.py)). On a
llama.cpp server the grammar constrains decoding itself: a malformed call is
*grammatically impossible*. Required argument keys are forced, enum values
become literal alternations, unknown tools cannot be named.

Since 3.0.0 the same forced-call path degrades gracefully on servers without
GBNF support (Ollama, LM Studio, cloud APIs): `response_format` with a
`json_schema` whose `name` field is an enum of the registered tools, then
plain `json_object`, then a text parse as the last resort.

**Honest scope.** Constrained decoding is not new — llama.cpp shipped
grammars in 2023, and cloud providers sell the same idea as "structured
outputs". The contribution is the integration: the grammar is *derived from
your tool schemas automatically* and wired as a retry safety net, so small
local models get the same call reliability that big APIs advertise. The
grammar guarantees a call's **form**, not the model's **judgment** — a model
can still pick the wrong tool; it just cannot emit a malformed one.

## Guarantee 2 — Answers cite sources, or say they can't

Grounded Q&A (`rag ask`, `kb ask`, the web UI's 📚 Sources) runs in an
**isolated prompt**: the retrieved chunks are presented as numbered sources
and the *only* system prompt is the grounding contract
([`scribe/prompts.py`](../scribe/prompts.py)) —

- every factual claim carries a `[n]` citation into the numbered sources;
- when sources disagree, the spot is tagged
  `[CONTRADICTION: source X vs source Y]` for a human to arbitrate;
- when the sources don't contain the answer, the model must refuse — even
  when the answer is common knowledge it could supply from its weights.

The isolation matters in practice: injecting sources into an ongoing
persona-laden conversation produced unreliable citing in our tests, while
the dedicated grounded turn holds the contract. Refusing an answerable
question is scored as failure, so the contract cannot be gamed by refusing
everything.

## Guarantee 3 — Grounding is measured, not asserted

Claims 1 and 2 would be marketing without an instrument. Scribe ships one:
the **Source-Presence Index** ([`scribe/evolve/spi.py`](../scribe/evolve/spi.py)),
a deterministic metric with **no LLM judge**:

- for an answerable task, SPI is the fraction of factual sentences carrying
  a valid `[n]` citation — out-of-range citations count as *uncited*, an
  invented source is worse than none;
- for an unanswerable task, SPI is 1.0 on a refusal and 0.0 on an "answer".

The held-out suite is **checksum-locked** (`MANIFEST.sha256`); Scribe's
self-evolution constitution forbids the agent from authoring its own eval.
When the original 8-task suite saturated (every strong model scored 1.000),
it was hardened to 24 tasks — multi-hop synthesis, cross-language grounding,
enumerations with distractor sources, and refusal traps where the answer is
famous but absent from the sources. A metric that can't fall can't measure.

### The leaderboard

`scribe-llm bench --models` runs the suite over any fleet defined in
`[scribe.bench]` config — local llama.cpp servers and cloud APIs side by
side, every model under the identical grounded prompt. From the first public
run (suite `b8dbabb216fc`, 2026-07-17, [full report](leaderboard.md)):

| Rank | Model | SPI |
| ---: | :--- | ---: |
| 1 | gemma-4-12B (local, llama.cpp) | **0.865** |
| 2 | llama-3.3-70b (Groq) | 0.826 |
| 3 | gpt-oss-120b (Groq) | 0.823 |
| 4 | qwen3-32b (Groq) | 0.807 |
| 5 | gemma-4-E2B (local, llama.cpp) | 0.664 |
| 6 | llama-3.1-8b (Groq) | 0.341 |

Two readings. First, **citation discipline does not scale with parameter
count**: a local 12B outperforms 70B and 120B cloud models on the same
tasks. Second, it doesn't come for free either — the 2B model keeps the
refusal discipline but loses citations on multi-sentence answers, and an
8B-class model largely ignores the contract. The harness sets the contract;
whether a model can hold it is an empirical, measurable property — which is
the point.

### Failure modes the hardened suite exposes

Even the best models lose SPI in three characteristic places: enumerations
(citations attached to some list items but not each sentence), derived
claims (a comparison computed from two sources, stated without citing
either), and adjacent-knowledge traps (asked about *firejail* with sources
describing *bubblewrap*, a model answers from its weights instead of
refusing).

## Reproducing

```bash
pip install scribe-llm
# configure your fleet
cat >> ~/.config/scribe/config.toml << 'TOML'
["scribe.bench"]
models = [
  { name = "my-local", base_url = "http://127.0.0.1:8080/v1", model = "default" },
  { name = "groq-70b", base_url = "https://api.groq.com/openai/v1",
    model = "llama-3.3-70b-versatile", api_key_env = "GROQ_API_KEY" },
]
TOML
scribe-llm bench --models   # writes docs/leaderboard.{md,json}
```

The suite checksum is printed with every run; results from different
checksums are not comparable. API keys travel through environment variables
only — nothing secret lands in config or output files.
