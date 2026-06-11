# 在 Windows 上通过 WSL 与 Ollama 运行 Scribe

🌐 [English](wsl_ollama_guide.md) · 简体中文

本指南介绍如何在 **WSL（适用于 Linux 的 Windows 子系统）** 中安装 Scribe，
并将其连接到本机上的 **Ollama** 模型。

---

## 🛠️ WSL 前置条件

新安装的 WSL（例如 Ubuntu）通常不会预装 Python 包管理器（`pip`）和
虚拟环境模块。在安装 Scribe 之前，请先在 WSL 终端中运行：

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
```

---

## 方案 A：直接在 WSL 内安装 Ollama（推荐，最简单）

在 WSL 内运行 Ollama 是最简单的方式，因为所有通信都走
`127.0.0.1`（localhost）；只要 Windows 上装好了显卡驱动，
Ollama 还会自动使用 GPU。

### 1. 在 WSL 中安装 Ollama
打开 WSL 终端（例如 Ubuntu），运行官方安装脚本：
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. 运行模型
将所需模型加载到 Ollama：
```bash
ollama run gemma2
```

### 3. 配置 Scribe
在 WSL 中创建或编辑配置文件 `~/.config/scribe/config.toml`：
```toml
[scribe]
base_url = "http://127.0.0.1:11434/v1"
model = "gemma2"
```
然后启动 Scribe：
```bash
scribe chat
```

---

## 方案 B：Ollama 在 Windows（宿主机）上运行，Scribe 在 WSL 中

如果你直接在 Windows 上安装了 Ollama 应用，WSL 默认无法通过
`127.0.0.1` 访问它，因为 WSL 有自己的虚拟网络。请按以下步骤操作：

### 1. 在 Windows 上配置 Ollama
必须让 Ollama 监听所有网络接口（而不仅仅是 localhost）：
1. 按 **Win + R**，输入 `sysdm.cpl` 并回车。
2. 切换到 **高级（Advanced）** 选项卡，点击 **环境变量（Environment Variables）**。
3. 在 *用户变量* 或 *系统变量* 下点击 **新建...** 并添加：
   * **变量名：** `OLLAMA_HOST`
   * **变量值：** `0.0.0.0`
4. 点击确定保存，然后在 Windows 上**完全退出并重新启动 Ollama 应用**
   （从系统托盘操作）。

### 2. 在 WSL 中查找 Windows 的 IP 地址
在 WSL 终端中运行以下命令，获取 Windows 宿主机的 IP 地址：
```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
```
*（示例输出：`172.25.80.1`）*

### 3. 在 WSL 中配置 Scribe
编辑 WSL 中的 `~/.config/scribe/config.toml`，将 `<WINDOWS_IP>`
替换为上一步获取的地址：
```toml
[scribe]
base_url = "http://172.25.80.1:11434/v1"  # 在这里填入你的 Windows IP
model = "gemma2"
```

### 4. Windows 11 的替代方案（镜像网络模式）
在 Windows 11 上也可以启用镜像网络模式。创建文件
`C:\Users\你的用户名\.wslconfig`，内容如下：
```ini
[wsl2]
networkingMode=mirrored
```
重启 WSL 后（在 PowerShell 中执行 `wsl --shutdown`），WSL 中的 Scribe
就可以直接通过 `http://127.0.0.1:11434/v1` 访问 Windows 上的 Ollama，
无需再查找 IP 地址！
