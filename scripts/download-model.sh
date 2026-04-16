#!/usr/bin/env bash
# download-model.sh — Download Gemma 4 E4B GGUF from Hugging Face
#
# Usage:
#   ./scripts/download-model.sh [output_dir]
#
# Default output dir: ~/models/cyberpaw/
#
# Requires: curl or wget

set -euo pipefail

OUTPUT_DIR="${1:-$HOME/models/cyberpaw}"
mkdir -p "$OUTPUT_DIR"

# Gemma 4 E4B Q4_K_M GGUF (≈3.5 GB)
# Update this URL when the official Gemma 4 GGUF is published on HF.
MODEL_FILENAME="gemma-4-e4b-q4_k_m.gguf"
# Placeholder URL — replace with the actual HF model repo URL
HF_REPO="google/gemma-4-e4b-it-GGUF"
HF_FILE="gemma-4-e4b-it-q4_k_m.gguf"
HF_URL="https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE"

DEST="$OUTPUT_DIR/$MODEL_FILENAME"

if [ -f "$DEST" ]; then
  echo "Model already exists: $DEST"
  echo "Delete it and re-run to re-download."
  exit 0
fi

echo "Downloading $HF_FILE → $DEST"
echo "Source: $HF_URL"
echo ""

if command -v curl &>/dev/null; then
  curl -L --progress-bar -o "$DEST" "$HF_URL"
elif command -v wget &>/dev/null; then
  wget --show-progress -O "$DEST" "$HF_URL"
else
  echo "Error: neither curl nor wget found."
  exit 1
fi

echo ""
echo "Model saved to: $DEST"
echo ""
echo "Next steps:"
echo "  1. Open CyberPaw"
echo "  2. Go to Settings → Model Path"
echo "  3. Set the path to: $DEST"
echo "  4. Restart the app"
