# Connecting Scribe to a model

🌐 English · [简体中文](providers.zh-CN.md)

Scribe talks to **any OpenAI-compatible endpoint**. That covers local servers
(llama.cpp, Ollama, LM Studio) and cloud providers (OpenRouter, Groq, OpenAI,
Mistral, ...). You configure three values:

```toml
# ~/.config/scribe/config.toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"   # where the server listens
model    = "default"                      # model name the server expects
api_key  = "not-needed"                   # only cloud providers need a real key
```

The same three are available as environment variables: `SCRIBE_BASE_URL`,
`SCRIBE_MODEL`, `SCRIBE_API_KEY`.

> **Model auto-detection:** when `model` is left as `"default"`, Scribe asks
> the server for its model list and uses the first one. llama.cpp ignores the
> field entirely; Ollama and LM Studio get the name of whatever model you have
> loaded. So in most local setups you never have to set `model` at all.

---

## llama.cpp (recommended for full control)

```bash
./scripts/start-server.sh          # uses MODEL_PATH, PORT, CTX_SIZE env vars
```

or by hand:

```bash
llama-server -m gemma-4-12b-it-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18083 \
  -c 131072 -ngl 99 --jinja
```

```toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"
model = "default"
reasoning = true     # llama.cpp + Gemma support native thinking
```

### Fitting Gemma 4 12B with 128k context into 12 GB VRAM

A 12 GB GPU (RTX 3060/4070 class) comfortably runs **Gemma 4 12B** as a
research/writing/coding daily driver. The weights at Q4_K_M take ~7 GB; the
rest of the budget goes to the KV cache, which at 128k context is what
actually decides whether you fit. Use a quantized KV cache:

```bash
llama-server -m gemma-4-12b-it-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18083 \
  -c 131072 -ngl 99 --jinja \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --flash-attn on
```

Guidelines:

- `-c 131072` — the full 128k window Scribe is configured for
  (`max_context_tokens = 131072`).
- `--cache-type-k q8_0 --cache-type-v q8_0` — halves KV memory vs f16 with
  negligible quality loss; required to fit 128k beside the weights in 12 GB.
- `--flash-attn on` — needed for quantized V-cache and faster long-context.
- If you still run out of memory, drop to `-c 65536` (64k) first — that is
  still enough for whole-book chapters — or offload a few layers with
  `-ngl 40` instead of 99.
- Smaller GPUs (8 GB): use Gemma 4 4B or a 7–9B model at Q4 with `-c 32768`.

## Ollama

```bash
ollama pull gemma4:12b      # or any other model
ollama serve                # usually already running as a service
```

```toml
[scribe]
base_url = "http://127.0.0.1:11434/v1"
model = "default"    # auto-resolves to the loaded model; or set "gemma4:12b"
reasoning = false    # Ollama has no chat_template_kwargs passthrough
```

By default Ollama truncates context to 4k; raise it for Scribe:

```bash
OLLAMA_CONTEXT_LENGTH=131072 ollama serve
```

On Windows, see the [WSL & Ollama guide](wsl_ollama_guide.md).

## LM Studio

Start the local server (default port 1234), load a model, then:

```toml
[scribe]
base_url = "http://127.0.0.1:1234/v1"
model = "default"
reasoning = false
```

## Cloud providers (API key)

Any OpenAI-compatible API works. Examples:

```toml
# OpenRouter — use any model id from openrouter.ai/models
[scribe]
base_url = "https://openrouter.ai/api/v1"
model = "google/gemma-4-26b-it"
api_key = "sk-or-..."
reasoning = false
```

```toml
# Groq
[scribe]
base_url = "https://api.groq.com/openai/v1"
model = "llama-3.3-70b-versatile"
api_key = "gsk_..."
reasoning = false
```

Prefer the environment variable over writing the key to disk:

```bash
export SCRIBE_API_KEY="sk-or-..."
```

---

# Web search engines

Scribe's `web_search` tool powers the research workflows:

- **No setup needed:** with no API key configured, search uses
  **DuckDuckGo** (HTML endpoint, no key, no account).
- **Brave Search (optional, better results):** set `BRAVE_API_KEY` in the
  environment, or `brave_api_key = "..."` under `[scribe]` in config.toml.
  If Brave errors out mid-session, Scribe falls back to DuckDuckGo
  automatically.

`web_fetch` retrieves and extracts readable text from any URL; no key needed.
