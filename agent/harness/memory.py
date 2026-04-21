"""
Agent Layer — Memory Consolidation (Gap 14 Simplified)
======================================================
Provides functions to update MEMORY.md with learned facts from a session.
"""

from __future__ import annotations

import os
import logging
from .subagent import run_subagent

log = logging.getLogger(__name__)

async def consolidate_session_memory(
    messages: list,
    backend,
    registry,
    working_directory: str,
    permission_mode,
    emit_fn,
    session_id: str,
) -> None:
    """
    Spawn a sub-agent to summarize what was learned in this session
    and append it to MEMORY.md (Gap 14 Simplified).
    """
    if not messages:
        return

    # Only consolidate if there was meaningful interaction
    if len(messages) < 4:
        return

    log.info("Starting memory consolidation for session %s", session_id)
    
    # We use a very specialized sub-agent for this
    summary_prompt = (
        "You are a memory consolidation sub-agent. Your task is to review the "
        "preceding conversation and identify 2-3 key technical facts, "
        "conventions, or project-specific details learned during this session. "
        "Write these facts as bullet points. "
        "Then, use the Write or Read/Edit tools to append these to a file named 'MEMORY.md' "
        "in the root directory. If the file doesn't exist, create it with a header '# Project Memory'. "
        "Be concise and technical. Do not include transient information like 'the user said hi'."
    )
    
    # Concatenate message history for the sub-agent
    history_text = "\n\n".join([
        f"{m.role.upper()}: {m.text_content()}" for m in messages
    ])
    
    task = f"{summary_prompt}\n\n--- CONVERSATION HISTORY ---\n\n{history_text}"
    
    try:
        # Run a specialized sub-agent that only has filesystem access
        await run_subagent(
            task=task,
            backend=backend,
            registry=registry,
            working_directory=working_directory,
            permission_mode=permission_mode,
            emit_fn=lambda _: None, # Silence consolidation tokens
            depth=1, # Consolidation is always depth 1
            label="memory-consolidation",
            tool_filter=["Read", "Write", "Edit", "MultiEdit"]
        )
    except Exception as e:
        log.warning("Memory consolidation failed: %s", e)
