"""
Build ID for deployment tracking.
Format: YYYY-MM-DD_N (date + sequential number for that day)
"""
from __future__ import annotations

import os
from pathlib import Path

_CACHED_BUILD_ID: str | None = None
_CACHED_MTIME: float | None = None
_BUILD_ID_FILE: Path | None = None

def get_build_id() -> str:
    """
    Return build id string for deployment verification.

    Priority:
    1) BUILD_ID file in project root (next to manage.py)
    2) env BUILD_ID
    3) "dev" fallback
    """
    global _CACHED_BUILD_ID, _CACHED_MTIME, _BUILD_ID_FILE
    # Check BUILD_ID file in project root (next to manage.py)
    if _BUILD_ID_FILE is None:
        base_dir = Path(__file__).resolve().parent.parent
        _BUILD_ID_FILE = base_dir / "BUILD_ID"
    build_id_file = _BUILD_ID_FILE
    if build_id_file.exists():
        try:
            mtime = build_id_file.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None and _CACHED_BUILD_ID and _CACHED_MTIME == mtime:
            return _CACHED_BUILD_ID
        try:
            value = build_id_file.read_text(encoding="utf-8").strip()
            if value:
                _CACHED_BUILD_ID = value
                _CACHED_MTIME = mtime
                return value
        except Exception:
            pass
    
    # Check env variable
    value = (os.environ.get("BUILD_ID") or "").strip()
    if value:
        return value
    
    # Fallback
    return "dev"


BUILD_ID = get_build_id()
