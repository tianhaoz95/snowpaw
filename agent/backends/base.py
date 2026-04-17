"""
Model Runner — Base Layer
=========================
Defines the abstract interface all LLM backends must implement.
The agent harness only ever talks to LLMBackend; concrete backends
are swapped in by the selector at startup.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable


@dataclass
class GenerateParams:
    """Hyperparameters forwarded to the model on each call."""
    max_new_tokens: int = 2048
    temperature: float = 0.2
    top_p: float = 0.95
    repetition_penalty: float = 1.1
    stop_sequences: list[str] = field(default_factory=lambda: [
        "<end_of_turn>",
    ])


class LLMBackend(abc.ABC):
    """
    Abstract base for all local LLM backends.

    Lifecycle
    ---------
    1. Instantiate (no I/O).
    2. Call ``load(model_path, on_progress)`` — blocks until the model is ready.
    3. Call ``generate(...)`` one or more times (streaming via async generator).
    4. Call ``unload()`` to free memory.

    All subclasses must be safe to call from a single asyncio event loop.
    Heavy blocking work (model loading, inference) should be wrapped in
    ``asyncio.to_thread`` inside the concrete implementation.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short human-readable backend name, e.g. 'llama.cpp' or 'AirLLM'."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def load(
        self,
        model_path: str,
        on_progress: Callable[[int], None],
    ) -> None:
        """
        Load the model from *model_path*.

        Parameters
        ----------
        model_path:
            Path to a GGUF file (llama.cpp).
        on_progress:
            Callback called with integer percentages 0–100 during loading.
            Implementations should call it at least at 0 and 100.
        """

    @abc.abstractmethod
    def is_loaded(self) -> bool:
        """Return True if the model is ready to generate."""

    @abc.abstractmethod
    def unload(self) -> None:
        """Release all model resources (weights, GPU memory, etc.)."""

    # ── Inference ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        params: GenerateParams,
    ) -> AsyncIterator[str]:
        """
        Stream generated tokens for *prompt*.

        Yields individual token strings as they are produced.
        Stops when the model emits an EOS token, a stop sequence, or
        ``params.max_new_tokens`` is reached.

        This is an *async generator* — callers use ``async for token in ...``.
        """

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def vram_used_mb(self) -> int:
        """Return approximate VRAM usage in MiB (0 if unknown)."""
        return 0

    def context_size(self) -> int:
        """Return the model's configured context window in tokens."""
        return 0
