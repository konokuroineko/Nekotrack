"""Optional native helpers with exact Python fallbacks.

The desktop app must remain usable when the native extension has not been built,
cannot be loaded, or is omitted from a portable/source installation.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Final

try:
    from _nekotrack_core import sequence_match_ratio as _native_sequence_match_ratio
except (ImportError, OSError):
    _native_sequence_match_ratio = None

RUST_AVAILABLE: Final[bool] = _native_sequence_match_ratio is not None
BACKEND_NAME: Final[str] = "rust" if RUST_AVAILABLE else "python"


def sequence_match_ratio(left: str, right: str) -> float:
    """Return difflib-compatible similarity, using Rust when available.

    This deliberately preserves SequenceMatcher's autojunk=False behavior.
    The Rust implementation is exercised against Python's reference algorithm
    in tests before it is enabled in release builds.
    """
    if _native_sequence_match_ratio is not None:
        return float(_native_sequence_match_ratio(left, right))
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def sequence_match_ratio_default(left: str, right: str) -> float:
    """Match SequenceMatcher's default autojunk=True behavior exactly.

    For right-hand strings shorter than 200 characters, difflib's autojunk
    heuristic is inactive, so the Rust autojunk=False implementation is
    equivalent. Longer right-hand strings stay on difflib to preserve the
    default popular-element heuristic.
    """
    left_text = str(left)
    right_text = str(right)
    if _native_sequence_match_ratio is not None and len(right_text) < 200:
        return float(_native_sequence_match_ratio(left_text, right_text))
    return SequenceMatcher(None, left_text, right_text).ratio()
