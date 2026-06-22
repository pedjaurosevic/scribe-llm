# Scribe Gauntlet Benchmark & Soak Test Results

To ensure Scribe's local-first guarantees hold under real-world conditions, the codebase is validated against a local automated gauntlet suite alongside the built-in SPI and Fitness benchmarks.

## Gauntlet Soak Test (June 22, 2026)

We ran a continuous **30-minute soak test** under heavy load to evaluate system stability, memory leaks, and response latency.

### Test Environment
* **Scribe Version**: 2.0.1
* **Local LLM Server**: `llama.cpp` serving `gemma-4-12B-it-Q4_K_M.gguf` at [http://127.0.0.1:18083/v1](http://127.0.0.1:18083/v1)
* **Hardware**: RTX 3060 12GB VRAM (~9.7 GB allocated)
* **Context Window**: 131,072 tokens
* **Grammar Enforcement**: Active (GBNF)
* **Sandbox Mode**: `bwrap` (Bubblewrap) active

### Performance & Pass Rate
* **Completed Runs**: 62
* **Total Checks**: 1,302
* **Failed Checks**: 0
* **Pass Rate**: **100.00%**
* **Average Run Duration**: ~13.2 seconds (fully stable from the first run `15.12s` to the last run `13.25s`, indicating zero performance drift or memory leaks).

---

## What is Verified in the Gauntlet?

Each of the 62 runs executed **21 automated checks** covering the core features of Scribe:

1. **Preflight Checks**:
   * CLI status contract matching (`scb status --json` matching Scribe 2.0.1 and warm runtime).
   * Fast model ping/pong check (average response time: **~0.3s**).

2. **GBNF Tool call grammar**:
   * Enforces that the model's generated JSON matches the JSON Schema for tool calls (`list_dir`, `read_file`, `make_dir`, `write_file`). A malformed tool call is rendered grammatically impossible.

3. **Local Web Fetching & Extraction**:
   * Markdown extraction from raw HTML page structures (ignoring scripts/nav).
   * Large page truncation safety checks.
   * Proper recovery of control tokens (`amber-lake-42`) in synthesized LLM summaries.

4. **RAG Grounding**:
   * Vector + FTS5 hybrid search retrieval correctness.
   * Grounded Q&A citations (ensures claims are appended with `[n]` referring to retrieved chunks).
   * Refusal safety (ensures the model states "do not cover" if facts aren't in the context).

5. **Sandbox & Security Boundaries**:
   * Workspace escape blocking (preventing `../` file access).
   * Destructive command interception (e.g., blocking `rm -rf $HOME`).
   * Normal read/write filesystem access within the workspace.

6. **Session & Transcript Indexing**:
   * SQLite-backed session checkpointing and restoration.
   * Full-text search retrieval across past session transcripts.

7. **Agent loop & Hard mode**:
   * plans and executes multi-page synthesis, detects contradictions between conflicting sources (marking them with `[CONTRADICTION]`), and runs a multi-step read-write workflow with exact content verification.

---

## Built-in Quality Gates

Scribe also includes two standard benchmark suites:

* **SPI Grounding (`scb bench --spi`)**: Evaluates grounded Q&A against a checksum-locked suite. Scores **SPI 1.00** on Gemma 4 12B.
* **Fitness (`scb bench --fitness`)**: Evaluates language and brevity on held-out tasks. Scores **Fitness 1.00** (100% language accuracy, 95% brevity kept).
