#!/usr/bin/env bash
# build-sidecar.sh — Build the Python sidecar binary and copy it to src-tauri/binaries/
#
# Usage:
#   ./scripts/build-sidecar.sh
#
# Requirements:
#   - Python 3.11+ with pip
#   - pyinstaller (pip install pyinstaller)
#   - All agent/requirements.txt deps installed
#
# The output binary is placed in src-tauri/binaries/ with the Tauri
# triple-suffix naming convention required by externalBin.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$REPO_ROOT/agent"
BINARIES_DIR="$REPO_ROOT/src-tauri/binaries"

# Resolve Python: prefer PYTHON_PATH env var (set by setup.sh), then auto-detect
if [ -n "${PYTHON_PATH:-}" ]; then
  PYTHON="$PYTHON_PATH"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "Error: Python 3 not found." >&2; exit 1
fi
echo "Using Python: $PYTHON ($($PYTHON --version))"

# Detect target triple
TARGET_TRIPLE=$(rustc -vV 2>/dev/null | awk '/^host:/ { print $2 }')
if [ -z "$TARGET_TRIPLE" ]; then
  OS=$(uname -s)
  ARCH=$(uname -m)
  case "$OS-$ARCH" in
    Darwin-arm64)  TARGET_TRIPLE="aarch64-apple-darwin" ;;
    Darwin-x86_64) TARGET_TRIPLE="x86_64-apple-darwin" ;;
    Linux-x86_64)  TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
    Linux-aarch64) TARGET_TRIPLE="aarch64-unknown-linux-gnu" ;;
    MINGW*|MSYS*)  TARGET_TRIPLE="x86_64-pc-windows-msvc" ;;
    *) echo "Unknown platform: $OS-$ARCH"; exit 1 ;;
  esac
fi

echo "Target triple: $TARGET_TRIPLE"

# Locate llama_cpp package dir so we can bundle its native .dylib/.so files
LLAMA_CPP_LIB_DIR=$("$PYTHON" -c "
import importlib.util, os
spec = importlib.util.find_spec('llama_cpp')
if spec and spec.origin:
    print(os.path.join(os.path.dirname(spec.origin), 'lib'))
" 2>/dev/null || true)

# Build PyInstaller args
PYINSTALLER_ARGS=(
  --onefile
  --name cyberpaw-agent
  --distpath "$AGENT_DIR/dist"
  --workpath "$AGENT_DIR/build"
  --specpath "$AGENT_DIR/build"
  --hidden-import asyncio
  --hidden-import json
  --hidden-import re
  --hidden-import psutil
  # Collect the entire llama_cpp package including its native libs
  --collect-all llama_cpp
)

# If we found the llama_cpp lib dir, add all dylib/so files explicitly too
# (belt-and-suspenders: --collect-all should handle it, but add-binary is
# more reliable for native shared libraries on macOS)
if [ -n "$LLAMA_CPP_LIB_DIR" ] && [ -d "$LLAMA_CPP_LIB_DIR" ]; then
  echo "Found llama_cpp lib dir: $LLAMA_CPP_LIB_DIR"
  for lib in "$LLAMA_CPP_LIB_DIR"/*.dylib "$LLAMA_CPP_LIB_DIR"/*.so; do
    [ -f "$lib" ] && PYINSTALLER_ARGS+=(--add-binary "$lib:llama_cpp/lib")
  done
else
  echo "Warning: llama_cpp lib dir not found — native libs may be missing from bundle"
fi

# Build with PyInstaller via the resolved Python
cd "$AGENT_DIR"
"$PYTHON" -m PyInstaller "${PYINSTALLER_ARGS[@]}" main.py

# Copy with Tauri's required naming convention
mkdir -p "$BINARIES_DIR"
DEST="$BINARIES_DIR/cyberpaw-agent-$TARGET_TRIPLE"

if [[ "$TARGET_TRIPLE" == *"windows"* ]]; then
  cp "$AGENT_DIR/dist/cyberpaw-agent.exe" "$DEST.exe"
  echo "Copied to: $DEST.exe"
else
  cp "$AGENT_DIR/dist/cyberpaw-agent" "$DEST"
  chmod +x "$DEST"
  echo "Copied to: $DEST"
fi

echo "Done. Run 'npm run tauri dev' to start the app."
