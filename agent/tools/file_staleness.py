"""
Agent Layer — File Staleness Guards
====================================
Stores the modification time of files when they are read by the model.
If the model tries to edit a file that has been modified since it was
last read, the edit is rejected.

Also tracks "written but not yet read" files: if the model calls Write
then immediately calls Edit without a Read in between, the Edit is
rejected with a message to Read first. This catches the common mistake
of writing a file and then trying to edit it using memorised content.
"""

from __future__ import annotations

import os

# (session_id, abs_path) -> mtime_at_read
_read_timestamps: dict[tuple[str, str], float] = {}

# Paths written this session that have not yet been read back.
# Key: (session_id, abs_path)
_written_unread: set[tuple[str, str]] = set()


def record_read(session_id: str, abs_path: str) -> None:
    """Record current mtime for *abs_path* and mark it as read."""
    try:
        _read_timestamps[(session_id, abs_path)] = os.path.getmtime(abs_path)
    except OSError:
        pass
    _written_unread.discard((session_id, abs_path))


def record_write(session_id: str, abs_path: str) -> None:
    """Mark *abs_path* as written-but-not-yet-read for this session."""
    try:
        _read_timestamps[(session_id, abs_path)] = os.path.getmtime(abs_path)
    except OSError:
        pass
    _written_unread.add((session_id, abs_path))


def is_stale(session_id: str, abs_path: str) -> bool:
    """Return True if *abs_path* has been modified since it was last recorded."""
    recorded = _read_timestamps.get((session_id, abs_path))
    if recorded is None:
        return False
    try:
        current = os.path.getmtime(abs_path)
        # 10ms tolerance for filesystem timestamp jitter
        return current > recorded + 0.01
    except OSError:
        return False


def is_written_unread(session_id: str, abs_path: str) -> bool:
    """Return True if *abs_path* was written this session but not yet read back."""
    return (session_id, abs_path) in _written_unread


def clear_staleness(session_id: str, abs_path: str) -> None:
    """Clear staleness record after a successful write/edit."""
    _read_timestamps.pop((session_id, abs_path), None)
    _written_unread.discard((session_id, abs_path))
