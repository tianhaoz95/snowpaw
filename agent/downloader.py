"""
Model Downloader
================
Downloads a model file from a URL (HuggingFace or direct) with:
- Streaming byte-count progress (emits download_progress events)
- Resume support (Range header if partial file exists)
- Cancellation via asyncio.Event
- SHA-256 checksum verification (optional)

All I/O is done with stdlib only (urllib, hashlib) wrapped in
asyncio.to_thread so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 256   # 256 KiB per read
PROGRESS_INTERVAL = 0.25  # seconds between progress events


# ── Model catalog ─────────────────────────────────────────────────────────────

@dataclass
class ModelEntry:
    id: str
    name: str
    description: str
    url: str
    filename: str
    size_gb: float
    quant: str
    sha256: str = ""       # optional checksum; empty = skip verification
    requires_hf_token: bool = False


# Curated list of locally-runnable models.
# All URLs verified publicly accessible (no HF token required) as of 2026-04.
MODEL_CATALOG: list[ModelEntry] = [
    ModelEntry(
        id="gemma-4-e2b-q4km",
        name="Gemma 4 E2B (Q4_K_M) — Recommended",
        description="2B MoE · 2.9 GB · Fastest · Good for 8 GB RAM machines",
        url="https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_K_M.gguf",
        filename="gemma-4-E2B-it-Q4_K_M.gguf",
        size_gb=2.9,
        quant="Q4_K_M",
    ),
    ModelEntry(
        id="gemma-4-e4b-q4km",
        name="Gemma 4 E4B (Q4_K_M)",
        description="4B MoE · 4.6 GB · Better quality · Needs 8+ GB RAM",
        url="https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf",
        filename="gemma-4-E4B-it-Q4_K_M.gguf",
        size_gb=4.6,
        quant="Q4_K_M",
    ),
    ModelEntry(
        id="qwen2.5-coder-3b-q4km",
        name="Qwen 2.5 Coder 3B (Q4_K_M)",
        description="3B · 2.0 GB · Strong code quality · Good for 8 GB RAM machines",
        url="https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        filename="qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        size_gb=2.0,
        quant="Q4_K_M",
    ),
    ModelEntry(
        id="qwen2.5-coder-7b-q4km",
        name="Qwen 2.5 Coder 7B (Q4_K_M)",
        description="7B · 4.4 GB · Excellent code quality · Needs 8+ GB RAM",
        url="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        size_gb=4.4,
        quant="Q4_K_M",
    ),
]


def get_catalog() -> list[dict]:
    """Return the catalog as a list of plain dicts (for JSON serialisation)."""
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "filename": m.filename,
            "size_gb": m.size_gb,
            "quant": m.quant,
            "requires_hf_token": m.requires_hf_token,
        }
        for m in MODEL_CATALOG
    ]


def find_model(model_id: str) -> ModelEntry | None:
    return next((m for m in MODEL_CATALOG if m.id == model_id), None)


# ── Download state ────────────────────────────────────────────────────────────

@dataclass
class DownloadState:
    model_id: str
    dest_path: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


# Global active download (one at a time)
_active: DownloadState | None = None


# ── Public API ────────────────────────────────────────────────────────────────

async def start_download(
    model_id: str,
    dest_dir: str,
    emit_fn: Callable[[dict], None],
    hf_token: str = "",
) -> None:
    """
    Start downloading *model_id* into *dest_dir*.

    Emits events:
      {"type": "download_progress", "model_id": "...", "pct": 0-100,
       "downloaded_mb": float, "total_mb": float, "speed_mbps": float}
      {"type": "download_done",   "model_id": "...", "path": "..."}
      {"type": "download_error",  "model_id": "...", "message": "..."}
      {"type": "download_cancelled", "model_id": "..."}
    """
    global _active

    if _active and _active.task and not _active.task.done():
        emit_fn({"type": "download_error", "model_id": model_id,
                 "message": "Another download is already in progress."})
        return

    entry = find_model(model_id)
    if entry is None:
        emit_fn({"type": "download_error", "model_id": model_id,
                 "message": f"Unknown model id: {model_id}"})
        return

    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, entry.filename)

    state = DownloadState(model_id=model_id, dest_path=dest_path)
    _active = state

    state.task = asyncio.create_task(
        _download_task(entry, dest_path, state.cancel_event, emit_fn, hf_token)
    )


def cancel_download() -> bool:
    """Cancel the active download. Returns True if one was running."""
    global _active
    if _active and _active.task and not _active.task.done():
        _active.cancel_event.set()
        return True
    return False


# ── Download task ─────────────────────────────────────────────────────────────

async def _download_task(
    entry: ModelEntry,
    dest_path: str,
    cancel: asyncio.Event,
    emit: Callable[[dict], None],
    hf_token: str,
) -> None:
    try:
        await _download(entry, dest_path, cancel, emit, hf_token)
    except asyncio.CancelledError:
        emit({"type": "download_cancelled", "model_id": entry.id})
    except Exception as exc:
        log.exception("Download failed for %s", entry.id)
        emit({"type": "download_error", "model_id": entry.id, "message": str(exc)})


async def _download(
    entry: ModelEntry,
    dest_path: str,
    cancel: asyncio.Event,
    emit: Callable[[dict], None],
    hf_token: str,
) -> None:
    loop = asyncio.get_event_loop()

    # Check existing partial file for resume
    existing_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

    headers: dict[str, str] = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    if existing_bytes > 0:
        headers["Range"] = f"bytes={existing_bytes}-"
        log.info("Resuming download from byte %d", existing_bytes)

    req = urllib.request.Request(entry.url, headers=headers)

    def _open_connection():
        return urllib.request.urlopen(req, timeout=30)

    try:
        response = await loop.run_in_executor(None, _open_connection)
    except urllib.error.HTTPError as e:
        if e.code == 416:
            # Range not satisfiable — file already complete
            emit({"type": "download_done", "model_id": entry.id, "path": dest_path})
            return
        if e.code == 401:
            if entry.requires_hf_token:
                raise RuntimeError(
                    "This model requires a HuggingFace token.\n"
                    "1. Accept the license at huggingface.co\n"
                    "2. Get your token at huggingface.co/settings/tokens\n"
                    "3. Paste it in the HF Token field and retry."
                )
            raise RuntimeError(
                "HTTP 401: Access denied. This model may require a HuggingFace token."
            )
        if e.code == 404:
            raise RuntimeError(
                f"HTTP 404: Model file not found at the download URL. "
                "The file may have been moved or renamed on HuggingFace."
            )
        raise RuntimeError(f"HTTP Error {e.code}: {e.reason}")

    content_length = int(response.headers.get("Content-Length", 0))
    total_bytes = existing_bytes + content_length if content_length else 0
    downloaded_bytes = existing_bytes

    # Emit initial progress
    emit({
        "type": "download_progress",
        "model_id": entry.id,
        "pct": 0,
        "downloaded_mb": round(downloaded_bytes / 1024 / 1024, 1),
        "total_mb": round(total_bytes / 1024 / 1024, 1) if total_bytes else None,
        "speed_mbps": 0.0,
        "resuming": existing_bytes > 0,
    })

    mode = "ab" if existing_bytes > 0 else "wb"
    hasher = hashlib.sha256() if entry.sha256 else None

    import time
    t_last = time.monotonic()
    bytes_since_last = 0

    with open(dest_path, mode) as f:
        while True:
            if cancel.is_set():
                response.close()
                emit({"type": "download_cancelled", "model_id": entry.id})
                return

            chunk = await loop.run_in_executor(None, response.read, CHUNK_SIZE)
            if not chunk:
                break

            f.write(chunk)
            if hasher:
                hasher.update(chunk)

            downloaded_bytes += len(chunk)
            bytes_since_last += len(chunk)

            now = time.monotonic()
            elapsed = now - t_last
            if elapsed >= PROGRESS_INTERVAL:
                speed = bytes_since_last / elapsed / 1024 / 1024  # MB/s
                pct = int(downloaded_bytes * 100 / total_bytes) if total_bytes else 0
                emit({
                    "type": "download_progress",
                    "model_id": entry.id,
                    "pct": min(pct, 99),
                    "downloaded_mb": round(downloaded_bytes / 1024 / 1024, 1),
                    "total_mb": round(total_bytes / 1024 / 1024, 1) if total_bytes else None,
                    "speed_mbps": round(speed, 2),
                })
                t_last = now
                bytes_since_last = 0

    response.close()

    # Verify checksum if provided
    if entry.sha256 and hasher:
        actual = hasher.hexdigest()
        if actual != entry.sha256:
            os.remove(dest_path)
            raise ValueError(
                f"Checksum mismatch: expected {entry.sha256[:16]}… got {actual[:16]}…"
            )

    emit({
        "type": "download_progress",
        "model_id": entry.id,
        "pct": 100,
        "downloaded_mb": round(downloaded_bytes / 1024 / 1024, 1),
        "total_mb": round(downloaded_bytes / 1024 / 1024, 1),
        "speed_mbps": 0.0,
    })
    emit({"type": "download_done", "model_id": entry.id, "path": dest_path})
    log.info("Download complete: %s → %s", entry.id, dest_path)
