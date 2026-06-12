# Scribe

🌐 [English](README.md) · 简体中文

[![CI](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/pedjaurosevic/scribe-ai/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> 本地优先的聊天 + 研究 + 编程智能体。可连接**任意** OpenAI 兼容服务器
> （llama.cpp、Ollama、LM Studio 或云端 API 密钥），借助网络搜索、RAG 和
> 语义记忆进行研究、写作与跨会话记忆。在 12 GB 显存的机器上即可流畅运行
> Gemma 4 12B（128k 上下文）。

## 功能特性

- **通用 LLM 适配器** — llama.cpp、Ollama、LM Studio，或任意 OpenAI 兼容的云端 API（OpenRouter、Groq 等）— 参见 [docs/providers.zh-CN.md](docs/providers.zh-CN.md)
- **网络研究** — `web_search` + `web_fetch` 工具；开箱即用（DuckDuckGo，无需 API 密钥），配置密钥后可升级为 Brave Search
- **写作智能体** — deep-research 和 writer 技能，可针对任意主题撰写书籍、论文和报告，并配有沙箱化的工作区文件工具
- **编程模式** — `/code` 将 Scribe 变为终端专家，提供完整的（逐条确认的）bash 访问
- **精美 TUI** — 漂亮的终端界面，支持流式输出、主题和实时推理走马灯
- **跨会话记忆** — SME（语义记忆引擎）实现无缝的会话连续性
- **RAG 集成** — 对你的文档库进行语义搜索
- **模块化技能** — 通过技能模块扩展能力
- **邮件桥** — 通过邮件接收结果，并从一个受信地址发送命令（仅用标准库）
- **维特根斯坦 + 皮尔士** — 受哲学启发的 harness 设计，让 LLM 行为更稳定

## 安装

### 🐧 Linux
```bash
# 克隆仓库
git clone https://github.com/pedjaurosevic/scribe-ai.git
cd scribe-ai

# 运行安装脚本：以可编辑模式安装包、创建配置，
# 并搭建 ~/scribe-workspace 工作区骨架。
./scripts/install.sh
```

### 🪟 Windows（WSL）
Scribe 可以通过 **WSL（适用于 Linux 的 Windows 子系统）** 在 Windows 上顺畅运行。
1. 打开你的 WSL 终端（例如 Ubuntu）。
2. 运行上面的 Linux 安装命令。
3. 要将 Scribe 与 **Ollama**（无论运行在 Windows 原生还是 WSL 内）配合使用，请参阅 [WSL 与 Ollama 集成指南](docs/wsl_ollama_guide.zh-CN.md)。

---

或者手动安装（跳过脚本）：

```bash
pip install -e .
```

> 需要 Python 3.10+。安装为可编辑模式，因此 `git pull` 即可原地更新 Scribe。

## 快速开始

1. 启动你的 llama-server：
```bash
./scripts/start-server.sh
```

2. 启动 Scribe：
```bash
scribe chat
```

3. Scribe 会自动回忆你的上一次会话，并询问是否继续。

## 配置

编辑 `~/.config/scribe/config.toml`：

```toml
[scribe]
base_url = "http://127.0.0.1:18083/v1"   # llama.cpp / Ollama / LM Studio / 云端
model = "default"                         # 自动检测已加载的模型
api_key = "not-needed"                    # 云服务商需要填写真实密钥
```

或使用环境变量：

```bash
export SCRIBE_BASE_URL=http://localhost:11434/v1   # 例如 Ollama
export SCRIBE_MODEL=gemma4:12b
export SCRIBE_API_KEY=sk-...                       # 仅云服务商需要
```

**完整的服务商指南** — llama.cpp、Ollama、LM Studio、OpenRouter/Groq，
以及在 **12 GB GPU 上以 128k 上下文运行 Gemma 4 12B** 的配方：
[docs/providers.zh-CN.md](docs/providers.zh-CN.md)。

**网络搜索**无需任何设置（DuckDuckGo）。如需 Brave Search，请设置
`BRAVE_API_KEY` 环境变量，或在 `[scribe]` 下配置 `brave_api_key`。

## CLI 命令

```bash
scribe chat                    # 交互式 TUI 聊天（默认流式输出）
scribe chat --textual          # 全屏 Textual UI（实验性）
scribe chat --resume TAG       # 恢复过去的会话（不带 TAG = 最近一次）
scribe web                     # Web UI，地址 http://localhost:8765

scribe memory recall "query"  # 从语义记忆中回忆
scribe rag search "query"     # 对已导入的文档进行语义搜索
scribe session last            # 显示最近一次会话
scribe session list            # 列出所有会话
scribe session search "query" # 对所有会话转录进行全文搜索

scribe config show             # 显示当前配置
scribe status                  # 检查系统状态
scribe evolve eval             # 运行 held-out 适应度测试集（Phase 0）

scribe mail send "Subj" "Body" # 给自己发送邮件通知
scribe mail watch              # 通过邮件接收命令（见下文）
```

## 邮件桥

Scribe 可以通过邮件向你发送结果，并接收邮件命令 — 仅使用 Python
标准库（无额外依赖）。

```toml
[scribe.email]
enabled = true
address = "you@gmail.com"
approved_sender = "you@gmail.com"   # 唯一允许向 Scribe 下达命令的地址
secret = "pick-a-token"             # 必须出现在命令邮件的主题中
```

```bash
export SCRIBE_EMAIL_PASSWORD="your-gmail-app-password"   # 切勿写进配置文件

scribe mail send "Done" "The report is ready."   # 发送一条通知
scribe mail watch                                 # 轮询收件箱、执行命令、回复
```

要执行命令，请给自己发一封主题中带有密钥的邮件：

> **主题：** `[scribe:pick-a-token] summarize the notes in research/`

Scribe 会使用**沙箱化的工作区工具**（读/写/列出文件，无 shell）执行命令，
并以邮件回复结果。

**安全性：** 仅当发件人匹配 `approved_sender` **且** 主题携带
`[scribe:secret]` 时，命令才会被接受。由于 `From:` 头可以被伪造，
密钥才是真正的关卡 — 将其留空即可关闭命令接收（发送功能仍然可用）。
Gmail 需要[应用专用密码](https://myaccount.google.com/apppasswords)
（需开启两步验证）。

## 架构

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

## 设计哲学

Scribe 建立在两大哲学支柱之上：

1. **维特根斯坦（Wittgenstein）** — 语言游戏定义意义。Scribe 使用显式的命令词汇表，让模型确切知道每个动作的含义。

2. **皮尔士（Peirce）** — 符号通过解释链获得意义。Scribe 保持符号学的连续性：每个回应都成为链条中的下一个符号。

## 许可证

MIT
