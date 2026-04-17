#!/usr/bin/env bash
# =============================================================================
# CyberPaw — setup.sh
# =============================================================================
# One-shot setup script. Run once from the repo root:
#
#   ./scripts/setup.sh
#
# What it does:
#   1. Checks system prerequisites (Rust, Node, Python 3.11+)
#   2. Installs npm dependencies
#   3. Installs Python dependencies (psutil + one LLM backend)
#   4. Builds the Python sidecar binary
#
# Options:
#   --backend llamacpp   Install llama-cpp-python (default, faster)
#   --backend airllm     Install airllm + transformers (low-memory)
#   --backend both       Install both backends
#   --metal              Enable Metal GPU acceleration for llama.cpp (macOS)
#   --skip-npm           Skip npm install
#   --skip-python        Skip Python dep install
#   --skip-sidecar       Skip sidecar build
#   --help               Show this message
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Defaults ──────────────────────────────────────────────────────────────────
BACKEND="llamacpp"
METAL=false
SKIP_NPM=false
SKIP_PYTHON=false
SKIP_SIDECAR=false

# ── Colours ───────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"
  RED="\033[31m"; CYAN="\033[36m"; RESET="\033[0m"
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

info()    { echo -e "${CYAN}▶${RESET} $*"; }
success() { echo -e "${GREEN}✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET} $*"; }
die()     { echo -e "${RED}✗${RESET} $*" >&2; exit 1; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --backend)   BACKEND="$2"; shift 2 ;;
    --metal)     METAL=true; shift ;;
    --skip-npm)  SKIP_NPM=true; shift ;;
    --skip-python) SKIP_PYTHON=true; shift ;;
    --skip-sidecar) SKIP_SIDECAR=true; shift ;;
    --help|-h)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Unknown option: $1. Run with --help for usage." ;;
  esac
done

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
echo "  ███████╗███╗   ██╗ ██████╗ ██╗    ██╗██████╗  █████╗ ██╗    ██╗"
echo "  ██╔════╝████╗  ██║██╔═══██╗██║    ██║██╔══██╗██╔══██╗██║    ██║"
echo "  ███████╗██╔██╗ ██║██║   ██║██║ █╗ ██║██████╔╝███████║██║ █╗ ██║"
echo "  ╚════██║██║╚██╗██║██║   ██║██║███╗██║██╔═══╝ ██╔══██║██║███╗██║"
echo "  ███████║██║ ╚████║╚██████╔╝╚███╔███╔╝██║     ██║  ██║╚███╔███╔╝"
echo "  ╚══════╝╚═╝  ╚═══╝ ╚═════╝  ╚══╝╚══╝ ╚═╝     ╚═╝  ╚═╝ ╚══╝╚══╝"
echo -e "${RESET}"
echo "  Local coding agent — setup"
echo ""

cd "$REPO_ROOT"

# =============================================================================
# STEP 1 — Prerequisites check
# =============================================================================
header "Step 1/4 — Checking prerequisites"

# Rust
if ! command -v rustc &>/dev/null; then
  die "Rust not found. Install it with:\n  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh\nthen re-run this script."
fi
RUST_VER=$(rustc --version | awk '{print $2}')
success "Rust $RUST_VER"

# Node.js ≥ 18
if ! command -v node &>/dev/null; then
  die "Node.js not found. Install it from https://nodejs.org (v18+)."
fi
NODE_VER=$(node --version)
NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 18 ]; then
  die "Node.js $NODE_VER is too old. Need v18+."
fi
success "Node.js $NODE_VER"

# npm
if ! command -v npm &>/dev/null; then
  die "npm not found (should come with Node.js)."
fi
success "npm $(npm --version)"

# Python 3.11+
PYTHON=""
for cmd in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
      PYTHON="$cmd"
      break
    fi
  fi
done
if [ -z "$PYTHON" ]; then
  die "Python 3.11+ not found. Install it from https://python.org."
fi
success "Python $($PYTHON --version)"

# pip (just needs to exist to create the venv)
if ! "$PYTHON" -m pip --version &>/dev/null 2>&1; then
  die "pip not available for $PYTHON. Try: $PYTHON -m ensurepip"
fi
success "pip available"

# macOS: check Xcode command line tools (needed for Rust/Tauri compilation)
if [ "$(uname)" = "Darwin" ]; then
  if ! xcode-select -p &>/dev/null; then
    warn "Xcode Command Line Tools not found. Installing..."
    xcode-select --install || true
    echo "  Re-run this script after the installation completes."
    exit 1
  fi
  success "Xcode CLT $(xcode-select -p)"
fi

# =============================================================================
# STEP 2 — npm install
# =============================================================================
header "Step 2/4 — Installing npm dependencies"

if $SKIP_NPM; then
  warn "Skipped (--skip-npm)"
else
  info "Running npm install..."
  npm install
  success "npm dependencies installed"
fi

# =============================================================================
# STEP 3 — Python virtual environment + dependencies
# =============================================================================
header "Step 3/4 — Installing Python dependencies"

VENV_DIR="$REPO_ROOT/.venv"

if $SKIP_PYTHON; then
  warn "Skipped (--skip-python)"
  # Still need to point at the venv python for the sidecar build
  if [ -f "$VENV_DIR/bin/python" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
  else
    VENV_PYTHON="$PYTHON"
  fi
else
  # Create venv if it doesn't exist yet
  if [ ! -f "$VENV_DIR/bin/python" ]; then
    info "Creating virtual environment at .venv/ ..."
    "$PYTHON" -m venv "$VENV_DIR"
    success "Virtual environment created"
  else
    success "Virtual environment already exists (.venv/)"
  fi

  VENV_PYTHON="$VENV_DIR/bin/python"
  PIP="$VENV_PYTHON -m pip install --quiet --upgrade"

  # Upgrade pip inside venv first (avoids old-pip warnings)
  "$VENV_PYTHON" -m pip install --quiet --upgrade pip

  # Core tools
  info "Installing psutil + PyInstaller..."
  $PIP psutil pyinstaller
  success "psutil, PyInstaller"

  # LLM backend(s)
  if [ "$BACKEND" != "llamacpp" ] && [ "$BACKEND" != "airllm" ] && [ "$BACKEND" != "both" ]; then
    die "Unknown --backend value: $BACKEND. Use 'llamacpp', 'airllm', or 'both'."
  fi

  if [ "$BACKEND" = "llamacpp" ] || [ "$BACKEND" = "both" ]; then
    info "Installing llama-cpp-python..."
    if $METAL && [ "$(uname)" = "Darwin" ]; then
      info "  (Metal GPU acceleration enabled)"
      CMAKE_ARGS="-DLLAMA_METAL=on" \
        "$VENV_PYTHON" -m pip install --quiet --upgrade --force-reinstall --no-cache-dir \
        llama-cpp-python
    else
      $PIP llama-cpp-python
    fi
    success "llama-cpp-python"
  fi

  if [ "$BACKEND" = "airllm" ] || [ "$BACKEND" = "both" ]; then
    info "Installing airllm + transformers + accelerate + huggingface-hub..."
    $PIP airllm transformers accelerate huggingface-hub
    success "airllm, transformers, accelerate, huggingface-hub"
  fi
fi

# =============================================================================
# STEP 4 — Build Python sidecar
# =============================================================================
header "Step 4/4 — Building Python sidecar binary"

if $SKIP_SIDECAR; then
  warn "Skipped (--skip-sidecar)"
else
  # Pass the venv python so build-sidecar.sh uses the right interpreter + deps
  PYTHON_PATH="$VENV_PYTHON" bash "$SCRIPT_DIR/build-sidecar.sh"
fi

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}Setup complete!${RESET}"
echo ""
echo "  To start the app in dev mode:"
echo -e "    ${CYAN}npm run tauri dev${RESET}"
echo ""
echo "  On first launch:"
echo "    1. Click ⚙ Settings"
echo "    2. Click '▼ Download a model…'"
echo "    3. Select a model and click Download"
echo "    4. Click 'Use this model' when done, then Save"
echo ""
