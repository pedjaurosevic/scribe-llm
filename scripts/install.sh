#!/usr/bin/env bash
# Install script for Scribe

set -e

echo "Installing Scribe..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python 3.10+ required. Found: $PYTHON_VERSION"
    exit 1
fi

# Check if pip is available
if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo "Error: 'pip' or 'pip3' is not installed. Please install Python package manager first."
    echo "On Debian/Ubuntu (WSL), you can install it using: sudo apt update && sudo apt install python3-pip"
    exit 1
fi

# Install the Python package (editable) from the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "Installing the 'scribe' package..."
if command -v pip &> /dev/null; then
    pip install -e "$REPO_ROOT"
else
    pip3 install -e "$REPO_ROOT"
fi

# Create config directory
CONFIG_DIR="$HOME/.config/scribe"
mkdir -p "$CONFIG_DIR"

# Copy example config if none exists
if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    if [ -f "$REPO_ROOT/config/config.example.toml" ]; then
        cp "$REPO_ROOT/config/config.example.toml" "$CONFIG_DIR/config.toml"
        echo "Created config at $CONFIG_DIR/config.toml"
    fi
fi

# Create state directories
mkdir -p "$HOME/.scribe/sessions"
mkdir -p "$HOME/.scribe/sme"
mkdir -p "$HOME/.scribe/rag"

# Scaffold the per-user workspace (the dir Scribe operates in). Each user gets a
# clean folder skeleton on first install; existing files are never overwritten.
WORKSPACE_DIR="${SCRIBE_WORKSPACE:-$HOME/scribe-workspace}"
mkdir -p "$WORKSPACE_DIR/research"
mkdir -p "$WORKSPACE_DIR/drafts"
mkdir -p "$WORKSPACE_DIR/wiki"
mkdir -p "$WORKSPACE_DIR/notes"
mkdir -p "$WORKSPACE_DIR/sessions"
if [ ! -f "$WORKSPACE_DIR/README.md" ]; then
    cat > "$WORKSPACE_DIR/README.md" <<'EOF'
# Scribe Workspace

This is your personal Scribe workspace. The agent reads and writes files here
(sandboxed to this directory unless you unlock /permissions).

- `research/` — gathered sources, raw findings
- `drafts/`   — work-in-progress writing
- `wiki/`     — durable notes Scribe maintains across sessions
- `notes/`    — scratch space
- `sessions/` — full Markdown transcript of every chat session (auto-written,
  searchable with `scribe session search "query"`)

Nothing here is committed to the Scribe source repo.
EOF
    echo "Scaffolded workspace at $WORKSPACE_DIR"
fi

echo "Installation complete!"
echo "Run 'scribe --help' to get started."
