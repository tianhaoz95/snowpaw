"""
Agent Layer — Permission System
================================
Three modes mirror claude-code's ToolPermissionContext but simplified
for local use.  When a tool requires permission in ASK mode, the
orchestrator emits a ``tool_ask`` event and suspends until it receives
a ``tool_ack`` response from the frontend via the NDJSON channel.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

log = logging.getLogger(__name__)


class PermissionMode(str, Enum):
    ASK = "ask"             # prompt for every non-read-only tool call
    AUTO_READ = "auto_read" # auto-approve reads; ask for writes/bash
    AUTO_ALL = "auto_all"   # allow everything silently


class PermissionDenied(Exception):
    """Raised when the user denies a tool call."""


class PermissionManager:
    """
    Manages pending permission requests.

    The orchestrator calls ``request_permission()`` which suspends the
    calling coroutine.  The main NDJSON loop calls ``resolve()`` when it
    receives a ``tool_ack`` message from the frontend.
    """

    def __init__(self) -> None:
        # id → asyncio.Future[bool]
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request_permission(
        self,
        request_id: str,
        emit_fn,          # callable(dict) — sends tool_ask to frontend
        tool_name: str,
        tool_input: dict,
    ) -> bool:
        """
        Emit a tool_ask event and wait for a tool_ack response.

        Returns True if the user approved, False if denied.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[request_id] = future

        emit_fn({
            "type": "tool_ask",
            "id": request_id,
            "tool": tool_name,
            "input": tool_input,
        })

        try:
            approved = await asyncio.wait_for(future, timeout=300.0)
        except asyncio.TimeoutError:
            log.warning("Permission request timed out: %s", request_id)
            approved = False
        finally:
            self._pending.pop(request_id, None)

        return approved

    def resolve(self, request_id: str, approved: bool) -> None:
        """Called when a tool_ack arrives from the frontend."""
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(approved)
