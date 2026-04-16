"""
Model Runner — Backend Selector
================================
Probes system capability at startup and picks the best backend.
The user can override the choice via the Settings page.

Selection logic
---------------
We use TOTAL RAM (not available) because the question is "can this
machine run a 4 GB model?" — not "is RAM free right now?". A developer
with 16 apps open still has a 24 GB machine.

Priority:
  1. If llama.cpp is installed and total RAM >= 8 GB → llama.cpp
  2. If airllm is installed                          → AirLLM
  3. Fallback to llama.cpp (will fail with a clear error if not installed)
"""

from __future__ import annotations

import logging
from enum import Enum

log = logging.getLogger(__name__)


class BackendKind(str, Enum):
    AUTO = "auto"
    LLAMACPP = "llamacpp"
    AIRLLM = "airllm"


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
    return 8.0  # safe default


def _total_vram_gb() -> float:
    """Return total VRAM in GB (0.0 if no discrete GPU / unknown)."""
    # macOS: read from system_profiler (total, not free)
    try:
        import re, subprocess  # noqa: E401
        out = subprocess.check_output(
            ["system_profiler", "SPDisplaysDataType"], text=True, timeout=5
        )
        m = re.search(r"VRAM.*?:\s*(\d+)\s*MB", out, re.IGNORECASE)
        if m:
            return int(m.group(1)) / 1024
    except Exception:
        pass
    # CUDA: total, not free
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


def _is_airllm_installed() -> bool:
    try:
        import airllm  # type: ignore[import]  # noqa: F401
        return True
    except ImportError:
        return False


def select_backend(
    kind: BackendKind,
    n_ctx: int = 8192,
) -> "LLMBackend":  # noqa: F821
    """
    Instantiate and return the appropriate backend.

    Parameters
    ----------
    kind:
        ``BackendKind.AUTO`` probes memory and decides automatically.
        Other values force a specific backend.
    n_ctx:
        Context window size passed to the backend constructor.
    """
    from .airllm_backend import AirLLMBackend
    from .llamacpp_backend import LlamaCppBackend

    if kind == BackendKind.LLAMACPP:
        log.info("Backend forced: llama.cpp")
        return LlamaCppBackend(n_ctx=n_ctx)

    if kind == BackendKind.AIRLLM:
        log.info("Backend forced: AirLLM")
        return AirLLMBackend(n_ctx=n_ctx)

    # AUTO — probe total memory and installed packages
    vram = _total_vram_gb()
    ram = _total_ram_gb()
    has_llamacpp = _is_llamacpp_installed()
    has_airllm = _is_airllm_installed()

    log.info(
        "Memory probe: total VRAM=%.1f GB, total RAM=%.1f GB | "
        "llama.cpp=%s, airllm=%s",
        vram, ram, has_llamacpp, has_airllm,
    )

    # llama.cpp: needs the package + enough RAM to hold the model
    # 8 GB total is comfortable for a 4 GB Q4_K_M model
    if has_llamacpp and (vram >= 4.0 or ram >= 8.0):
        log.info("Auto-selected backend: llama.cpp (RAM=%.1f GB)", ram)
        return LlamaCppBackend(n_ctx=n_ctx)

    if has_airllm:
        log.info("Auto-selected backend: AirLLM (low memory or llama.cpp missing)")
        return AirLLMBackend(n_ctx=n_ctx)

    # Neither installed — default to llama.cpp so the error message is clear
    log.warning(
        "Neither llama-cpp-python nor airllm is installed. "
        "Defaulting to llama.cpp — load will fail with an install hint."
    )
    return LlamaCppBackend(n_ctx=n_ctx)
