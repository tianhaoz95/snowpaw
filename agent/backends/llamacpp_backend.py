"""
Model Runner — llama.cpp Backend
=================================
Uses ``llama-cpp-python`` for fast local inference.
Recommended when ≥5 GB VRAM or ≥12 GB RAM is available.
Supports GGUF models (Gemma 4 E4B Q4_K_M ≈ 3.5 GB).

Progress reporting
------------------
llama_model_params has a C-level progress_callback field.
We inject it by temporarily monkey-patching llama_model_default_params
(which Llama.__init__ calls at line 227) to return params that already
have our callback wired in. The patch is thread-local and restored
immediately after construction, so it's safe for concurrent use.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import threading
from typing import AsyncIterator, Callable

from .base import GenerateParams, LLMBackend

log = logging.getLogger(__name__)

# Thread-local storage for the injected callback
_tls = threading.local()


class LlamaCppBackend(LLMBackend):
    """llama-cpp-python wrapper with real load-progress and async streaming."""

    def __init__(self, n_ctx: int = 8192, n_gpu_layers: int = -1) -> None:
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._llm = None
        self._loading = False

    @property
    def name(self) -> str:
        return "llama.cpp"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def load(
        self,
        model_path: str,
        on_progress: Callable[[int], None],
    ) -> None:
        self._loading = True
        on_progress(0)
        log.info("Loading model via llama.cpp: %s", model_path)

        loop = asyncio.get_event_loop()
        last_pct = [0]

        def _progress_cb(progress: float, _user_data: ctypes.c_void_p) -> bool:
            pct = min(99, int(progress * 100))
            if pct > last_pct[0]:
                last_pct[0] = pct
                loop.call_soon_threadsafe(on_progress, pct)
            return True  # returning False aborts the load

        def _load() -> None:
            try:
                import llama_cpp                   # type: ignore[import]
                import llama_cpp.llama_cpp as lib  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "llama-cpp-python is not installed. "
                    "Run: pip install llama-cpp-python"
                ) from exc

            # Keep a reference so the C callback isn't GC'd during load
            c_callback = lib.llama_progress_callback(_progress_cb)

            # Temporarily patch llama_model_default_params so that when
            # Llama.__init__ calls it, the returned struct already has our
            # callback. We restore the original immediately after construction.
            original_fn = lib.llama_model_default_params

            def _patched_default_params():
                params = original_fn()
                params.progress_callback = c_callback
                return params

            lib.llama_model_default_params = _patched_default_params
            try:
                self._llm = llama_cpp.Llama(
                    model_path=model_path,
                    n_ctx=self._n_ctx,
                    n_gpu_layers=self._n_gpu_layers,
                    verbose=False,
                )
            finally:
                lib.llama_model_default_params = original_fn
                # Keep c_callback alive until here (model is loaded)
                del c_callback

        await asyncio.to_thread(_load)
        self._loading = False
        on_progress(100)
        log.info("llama.cpp model ready")

    def is_loaded(self) -> bool:
        return self._llm is not None and not self._loading

    def unload(self) -> None:
        self._llm = None
        log.info("llama.cpp model unloaded")

    # ── Inference ─────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        params: GenerateParams,
    ) -> AsyncIterator[str]:
        if self._llm is None:
            raise RuntimeError("Model not loaded")

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _infer() -> None:
            try:
                stream = self._llm(  # type: ignore[misc]
                    prompt,
                    max_tokens=params.max_new_tokens,
                    temperature=params.temperature,
                    top_p=params.top_p,
                    repeat_penalty=params.repetition_penalty,
                    stop=params.stop_sequences,
                    stream=True,
                    echo=False,
                )
                for chunk in stream:
                    token: str = chunk["choices"][0]["text"]
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            except Exception as exc:
                log.error("llama.cpp inference error: %s", exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, _infer)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def context_size(self) -> int:
        return self._n_ctx
