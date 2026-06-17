# Running Scribe on Windows via WSL with Ollama

🌐 English · [简体中文](wsl_ollama_guide.zh-CN.md)

This guide explains how to install Scribe inside **WSL (Windows Subsystem for
Linux)** and connect it to **Ollama** models on your local machine.

---

## 🛠️ WSL prerequisites

A fresh WSL install (e.g. Ubuntu) usually does not ship with the Python
package manager (`pip`) or the virtual-environment module preinstalled.
Before installing Scribe, run this in your WSL terminal:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv
```

---

## Scenario A: Install Ollama directly inside WSL (recommended and easiest)

Running Ollama inside WSL is the simplest setup because everything talks over
`127.0.0.1` (localhost), and Ollama automatically uses your GPU if the
drivers are installed on Windows.

### 1. Install Ollama in WSL
Open your WSL terminal (e.g. Ubuntu) and run the official install script:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Run a model
Load the model you want into Ollama:
```bash
ollama run gemma2
```

### 3. Configure Scribe
In WSL, create or edit the config file `~/.config/scribe/config.toml`:
```toml
[scribe]
base_url = "http://127.0.0.1:11434/v1"
model = "gemma2"
```
Then start Scribe with:
```bash
scribe-llm chat
```

---

## Scenario B: Ollama runs on Windows (host), Scribe in WSL

If you have the Ollama app installed directly on Windows, WSL cannot reach it
at `127.0.0.1` by default because WSL has its own virtual network. Apply the
following steps:

### 1. Configure Ollama on Windows
You must make Ollama listen on all network interfaces (not just localhost):
1. Press **Win + R**, type `sysdm.cpl` and press Enter.
2. Go to the **Advanced** tab and click **Environment Variables**.
3. Under *User variables* or *System variables* click **New...** and add:
   * **Variable name:** `OLLAMA_HOST`
   * **Variable value:** `0.0.0.0`
4. Click OK, save, and **fully quit and restart the Ollama app** on Windows
   (from the system tray).

### 2. Find the Windows IP address from WSL
From your WSL terminal, get the Windows host's IP address by running:
```bash
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
```
*(Example output: `172.25.80.1`)*

### 3. Configure Scribe in WSL
Edit `~/.config/scribe/config.toml` in WSL and replace `<WINDOWS_IP>` with the
address you got in the previous step:
```toml
[scribe]
base_url = "http://172.25.80.1:11434/v1"  # put your Windows IP here
model = "gemma2"
```

### 4. Windows 11 alternative (mirrored networking)
On Windows 11 you can enable mirrored networking mode instead. Create the
file `C:\Users\YourName\.wslconfig` with the following content:
```ini
[wsl2]
networkingMode=mirrored
```
After restarting WSL (`wsl --shutdown` from PowerShell), Scribe inside WSL
can reach Ollama on Windows via plain `http://127.0.0.1:11434/v1` — no IP
hunting needed!
