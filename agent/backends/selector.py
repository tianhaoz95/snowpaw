"""
Model Runner — Backend Selector
================================
Probes system capability at startup and picks the best backend.
The user can override the choice via the Settings page.

Only llama.cpp is supported. It requires a GGUF model file.
"""

from __future__ import annotations

import logging
import os
import re
from enum import Enum

log = logging.getLogger(__name__)

# Fraction of total RAM budgeted for the model + KV cache combined.
# 0.75 leaves ~25% for the OS, browser, IDE, and other apps.
_RAM_UTILISATION = 0.75

# KV cache cost in bytes per token.
# Formula: n_layers × kv_heads × head_dim × 2 (K+V) × 2 bytes (f16)
# Known values for supported models (conservative — actual may be slightly lower):
#   Gemma 4 E2B  (26L, 4kv,  256d) → 106,496 B/tok
#   Gemma 4 E4B  (34L, 4kv,  256d) → 139,264 B/tok
#   Qwen2.5 3B   (36L, 2kv,  128d) →  36,864 B/tok
#   Qwen2.5 7B   (28L, 4kv,  128d) →  57,344 B/tok
# For unknown models we fall back to a conservative 80 KB/token (roughly
# equivalent to a ~3B GQA model). Better to leave ctx headroom than OOM.
_KV_BYTES_PER_TOKEN_KNOWN: dict[str, int] = {
    "gemma-4-e2b": 106_496,
    "gemma-4-e4b": 139_264,
    "qwen2.5-coder-3b": 36_864,
    "qwen2.5-coder-7b": 57_344,
    "qwen2.5-3b": 36_864,
    "qwen2.5-7b": 57_344,
}
_KV_BYTES_PER_TOKEN_DEFAULT = 80_000  # conservative fallback

# Hard bounds
_CTX_MIN = 4_096
_CTX_MAX = 131_072   # 128k — llama.cpp hard cap for most models


class BackendKind(str, Enum):
    AUTO = "auto"
    LLAMACPP = "llamacpp"


def _total_ram_gb() -> float:
    """Return total installed RAM in GB."""
    try:
        import psutil  # type: ignore[import]
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 ** 2)
    except Exception:
        pass
    return 8.0


def _total_vram_gb() -> float:
    """Return total VRAM in GB (0.0 if no discrete GPU / unknown)."""
    try:
        out = __import__("subprocess").check_output(
            ["system_profiler", "SPDisplaysDataType"], text=True, timeout=5
        )
        m = re.search(r"VRAM.*?:\s*(\d+)\s*MB", out, re.IGNORECASE)
        if m:
            return int(m.group(1)) / 1024
    except Exception:
        pass
    try:
        import torch  # type: ignore[import]
        if torch.cuda.is_available():
            _, total = torch.cuda.mem_get_info()
            return total / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def _is_llamacpp_installed() -> bool:
    try:
        import llama_cpp  # type: ignore[import]  # noqa: F401
        return True
    except ImportError:
        return False


def _model_size_gb(model_path: str) -> float:
    """
    Estimate model weight size in GB.
    Tries the file size on disk first; falls back to parsing the filename
    for a parameter count hint (e.g. '7b', '3b', '2b').
    """
    if model_path and os.path.isfile(model_path):
        try:
            return os.path.getsize(model_path) / (1024 ** 3)
        except OSError:
            pass

    # Parse parameter count from filename: "7b", "3b", "2b", "14b", etc.
    name = os.path.basename(model_path).lower() if model_path else ""
    m = re.search(r"(\d+(?:\.\d+)?)b", name)
    if m:
        params_b = float(m.group(1))
        # Q4_K_M ≈ 0.55 bytes per parameter
        return params_b * 0.55
    return 3.0  # conservative fallback (covers Gemma 4 E2B Q4_K_M ≈ 2.9 GB)


def _kv_bytes_per_token(model_path: str) -> int:
    """Look up KV cache bytes/token for a known model, else return the default."""
    name = os.path.basename(model_path).lower()
    for key, bpt in _KV_BYTES_PER_TOKEN_KNOWN.items():
        if key in name:
            return bpt
    return _KV_BYTES_PER_TOKEN_DEFAULT


def calculate_context_size(ram_gb: float, model_path: str = "") -> int:
    """
    Calculate the largest safe context window for the available hardware.

    Strategy
    --------
    1. Budget = total_ram × RAM_UTILISATION  (leaves 25% for OS + other apps)
    2. Subtract model weight size from budget → KV cache headroom.
    3. KV cache headroom / bytes_per_token → raw n_ctx.
    4. Round down to the nearest power of two (llama.cpp cache alignment).
    5. Clamp to [CTX_MIN, CTX_MAX].
    """
    model_gb = _model_size_gb(model_path)
    bytes_per_token = _kv_bytes_per_token(model_path)

    budget_gb = ram_gb * _RAM_UTILISATION
    kv_budget_gb = max(0.25, budget_gb - model_gb)

    kv_budget_bytes = kv_budget_gb * (1024 ** 3)
    raw_ctx = int(kv_budget_bytes / bytes_per_token)

    # Round down to nearest power of two for llama.cpp cache alignment
    ctx = _CTX_MIN
    while ctx * 2 <= raw_ctx and ctx * 2 <= _CTX_MAX:
        ctx *= 2

    log.info(
        "Context size: RAM=%.1fGB model=%.1fGB budget=%.1fGB "
        "kv_budget=%.1fGB bytes/tok=%d raw_ctx=%d → n_ctx=%d",
        ram_gb, model_gb, budget_gb, kv_budget_gb, bytes_per_token, raw_ctx, ctx,
    )
    return ctx


def calculate_max_new_tokens(n_ctx: int) -> int:
    """
    Return the max tokens the model may generate per turn.

    This is independent of n_ctx — max_new_tokens only stops generation early,
    it has no effect on KV cache allocation or prefill cost. The right value
    for a coding agent is simply large enough to never cut off a real response.
    4096 covers all realistic prose + code blocks; we cap at 8192 as a
    runaway-generation safety net.
    """
    return min(max(4096, n_ctx // 32), 8192)


def select_backend(
    kind: BackendKind,
    n_ctx: int = 0,
    model_path: str = "",
) -> "LLMBackend":  # noqa: F821
    """
    Instantiate and return the appropriate backend.

    Parameters
    ----------
    kind:
        ``BackendKind.AUTO`` probes memory and decides automatically.
        Other values force a specific backend.
    n_ctx:
        Context window size. If 0 (default), auto-calculated from available RAM.
    model_path:
        Path to the model file — used to estimate model weight size for the
        context window calculation.
    """
    from .llamacpp_backend import LlamaCppBackend

    log.info("Selecting backend (kind=%s)", kind)

    vram = _total_vram_gb()
    ram = _total_ram_gb()
    has_llamacpp = _is_llamacpp_installed()

    log.info(
        "Auto-selection probe: VRAM=%.1fGB, RAM=%.1fGB | llama.cpp=%s",
        vram, ram, has_llamacpp,
    )

    if n_ctx == 0:
        n_ctx = calculate_context_size(ram, model_path)

    return LlamaCppBackend(n_ctx=n_ctx)
