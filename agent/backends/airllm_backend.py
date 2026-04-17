"""
Model Runner — AirLLM Backend
==============================
Uses the ``airllm`` package for layer-by-layer inference.
Enables running large models on machines with only ~4 GB RAM by
loading transformer layers one at a time instead of all at once.

Slower (~3 tok/s on CPU) but works on base MacBook Air M1 / 8 GB RAM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

from .base import GenerateParams, LLMBackend

log = logging.getLogger(__name__)


class AirLLMBackend(LLMBackend):
    """AirLLM wrapper for memory-constrained inference."""

    def __init__(self, n_ctx: int = 4096) -> None:
        self._n_ctx = n_ctx
        self._model = None  # airllm.AutoModel instance
        self._tokenizer = None

    @property
    def name(self) -> str:
        return "AirLLM"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def load(
        self,
        model_path: str,
        on_progress: Callable[[int], None],
    ) -> None:
        on_progress(0)
        log.info("Loading model via AirLLM: %s", model_path)

        def _load() -> None:
            try:
                from airllm import AutoModel  # type: ignore[import]
                from transformers import AutoTokenizer  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "airllm and/or transformers not installed. "
                    "Run: pip install airllm transformers"
                ) from exc

            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            
            # If the model is already 4-bit quantized (indicated by our filename convention),
            # we don't need to apply additional compression during load.
            compression = "4bit"
            if "airllm-4bit" in model_path:
                compression = None
                log.info("Model already 4-bit, skipping on-the-fly compression")

            # AirLLM loads layers on demand; this call sets up the model
            # without pulling all weights into memory at once.
            self._model = AutoModel.from_pretrained(
                model_path,
                compression=compression,
            )

        await asyncio.to_thread(_load)
        on_progress(100)
        log.info("AirLLM model ready")

    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        log.info("AirLLM model unloaded")

    # ── Inference ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        params: GenerateParams,
    ) -> AsyncIterator[str]:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Model not loaded")

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _infer() -> None:
            try:
                input_ids = self._tokenizer(
                    prompt, return_tensors="pt"
                ).input_ids

                # AirLLM generate returns a list of token-id tensors
                # when streaming=True (if supported) or a full tensor.
                # We iterate token by token for a streaming experience.
                generated = self._model.generate(
                    input_ids,
                    max_new_tokens=params.max_new_tokens,
                    temperature=params.temperature,
                    top_p=params.top_p,
                    repetition_penalty=params.repetition_penalty,
                    do_sample=params.temperature > 0,
                )
                # Decode only the newly generated tokens
                new_ids = generated[0][input_ids.shape[-1]:]
                for tok_id in new_ids:
                    # skip_special_tokens=False so we can detect <end_of_turn>
                    token = self._tokenizer.decode(
                        [tok_id], skip_special_tokens=False
                    )
                    if any(s in token for s in params.stop_sequences):
                        break
                    # Re-decode with special tokens stripped for clean output
                    clean = self._tokenizer.decode(
                        [tok_id], skip_special_tokens=True
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, clean)
            except Exception as exc:
                log.error("AirLLM inference error: %s", exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.get_event_loop().run_in_executor(None, _infer)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def context_size(self) -> int:
        return self._n_ctx
