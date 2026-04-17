"""
Model Runner — Backend Selector
================================
Probes system capability at startup and picks the best backend.
The user can override the choice via the Settings page.

Only llama.cpp is supported. It requires a GGUF model file.
"""

from __future__ import annotations

import logging
from enum import Enum

log = logging.getLogger(__name__)


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
    return 8.0  # safe default


def _total_vram_gb() -> float:
    """Return total VRAM in GB (0.0 if no discrete GPU / unknown)."""
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


def select_backend(
    kind: BackendKind,
    n_ctx: int = 8192,
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
        Context window size passed to the backend constructor.
    model_path:
        Optional path to the model (unused, kept for API compatibility).
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

    return LlamaCppBackend(n_ctx=n_ctx)
