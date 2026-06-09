#!/usr/bin/env bash
# Example llama-server launcher for Scribe
#
# This script shows how to start llama-server with appropriate settings.
# Adjust paths and parameters for your setup.

set -e

# Configuration
MODEL_PATH="${MODEL_PATH:-$HOME/llama.cpp/models/gemma-4-12B-it-Q4_K_M.gguf}"
PORT="${PORT:-18083}"
HOST="${HOST:-127.0.0.1}"
CTX_SIZE="${CTX_SIZE:-131072}"
GPU_LAYERS="${GPU_LAYERS:-99}"

# Find llama-server
if [ -f "$HOME/llama.cpp/build/bin/llama-server" ]; then
    LLAMA_SERVER="$HOME/llama.cpp/build/bin/llama-server"
elif command -v llama-server &> /dev/null; then
    LLAMA_SERVER="llama-server"
else
    echo "Error: llama-server not found"
    exit 1
fi

echo "Starting llama-server..."
echo "  Model: $MODEL_PATH"
echo "  Port: $PORT"
echo "  Context: $CTX_SIZE"
echo "  GPU Layers: $GPU_LAYERS"

exec "$LLAMA_SERVER" \
    -m "$MODEL_PATH" \
    --host "$HOST" \
    --port "$PORT" \
    -ngl "$GPU_LAYERS" \
    -c "$CTX_SIZE" \
    -ctk q8_0 \
    -ctv q8_0 \
    -np 1 \
    --flash-attn \
    -b 2048 \
    -ub 512 \
    -t 6 \
    --mlock \
    --no-mmap \
    --jinja \
    --temp 1.0 \
    --top-p 0.95 \
    --top-k 64 \
    --reasoning off \
    --metrics \
    --slots \
    --log-timestamps \
    --log-prefix
