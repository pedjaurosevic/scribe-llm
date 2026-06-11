# 将 Scribe 连接到模型

🌐 [English](providers.md) · 简体中文

Scribe 可与**任意 OpenAI 兼容端点**通信，涵盖本地服务器
（llama.cpp、Ollama、LM Studio）和云服务商（OpenRouter、Groq、OpenAI、
Mistral 等）。你只需配置三个值：

```toml
# ~/.config/scribe/config.toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"   # 服务器监听地址
model    = "default"                      # 服务器期望的模型名
api_key  = "not-needed"                   # 仅云服务商需要真实密钥
```

这三项也可以通过环境变量设置：`SCRIBE_BASE_URL`、
`SCRIBE_MODEL`、`SCRIBE_API_KEY`。

> **模型自动检测：** 当 `model` 保持为 `"default"` 时，Scribe 会向服务器
> 查询模型列表并使用第一个。llama.cpp 完全忽略该字段；Ollama 和
> LM Studio 则会收到你已加载模型的名称。因此在大多数本地部署中，
> 你根本不需要设置 `model`。

---

## llama.cpp（推荐，可完全掌控）

```bash
./scripts/start-server.sh          # 使用 MODEL_PATH、PORT、CTX_SIZE 环境变量
```

或手动启动：

```bash
llama-server -m gemma-4-12b-it-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18083 \
  -c 131072 -ngl 99 --jinja
```

```toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"
model = "default"
reasoning = true     # llama.cpp + Gemma 支持原生思考（thinking）
```

### 在 12 GB 显存中装下 Gemma 4 12B 与 128k 上下文

一块 12 GB 的 GPU（RTX 3060/4070 级别）足以将 **Gemma 4 12B** 作为
研究/写作/编程的日常主力。Q4_K_M 量化的权重约占 7 GB；其余预算都
留给 KV 缓存 — 在 128k 上下文下，KV 缓存才是能否装下的决定因素。
请使用量化的 KV 缓存：

```bash
llama-server -m gemma-4-12b-it-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18083 \
  -c 131072 -ngl 99 --jinja \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --flash-attn on
```

要点：

- `-c 131072` — Scribe 配置的完整 128k 窗口
  （`max_context_tokens = 131072`）。
- `--cache-type-k q8_0 --cache-type-v q8_0` — 相比 f16 将 KV 内存减半，
  质量损失可忽略；要在 12 GB 中同时装下权重和 128k 上下文，这是必需的。
- `--flash-attn on` — 量化 V 缓存所必需，同时加速长上下文。
- 如果仍然显存不足，先降到 `-c 65536`（64k）— 这仍足以容纳整本书的
  章节；或者用 `-ngl 40` 代替 99，将部分层卸载到 CPU。
- 更小的 GPU（8 GB）：使用 Gemma 4 4B 或 7–9B 的 Q4 模型，配 `-c 32768`。

## Ollama

```bash
ollama pull gemma4:12b      # 或其他任意模型
ollama serve                # 通常已作为服务在运行
```

```toml
[scribe]
base_url = "http://127.0.0.1:11434/v1"
model = "default"    # 自动解析为已加载的模型；也可显式设置 "gemma4:12b"
reasoning = false    # Ollama 不支持 chat_template_kwargs 透传
```

Ollama 默认将上下文截断为 4k；为 Scribe 调高它：

```bash
OLLAMA_CONTEXT_LENGTH=131072 ollama serve
```

在 Windows 上，请参阅 [WSL 与 Ollama 指南](wsl_ollama_guide.zh-CN.md)。

## LM Studio

启动本地服务器（默认端口 1234），加载一个模型，然后：

```toml
[scribe]
base_url = "http://127.0.0.1:1234/v1"
model = "default"
reasoning = false
```

## 云服务商（API 密钥）

任何 OpenAI 兼容的 API 都可以使用。示例：

```toml
# OpenRouter — 可使用 openrouter.ai/models 上的任意模型 id
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

优先使用环境变量，而不是把密钥写到磁盘上：

```bash
export SCRIBE_API_KEY="sk-or-..."
```

---

# 网络搜索引擎

Scribe 的 `web_search` 工具为研究工作流提供支持：

- **无需任何设置：** 未配置 API 密钥时，搜索使用
  **DuckDuckGo**（HTML 端点，无需密钥，无需账号）。
- **Brave Search（可选，结果更好）：** 在环境变量中设置 `BRAVE_API_KEY`，
  或在 config.toml 的 `[scribe]` 下设置 `brave_api_key = "..."`。
  如果 Brave 在会话中途出错，Scribe 会自动回退到 DuckDuckGo。

`web_fetch` 可从任意 URL 抓取并提取可读文本；无需密钥。
