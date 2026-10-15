"""Added lines of a change, in memory only (T053; research R11). Line text is never logged or stored.

The parsers live in `gcattr.diff`, shared with `gca attribute` (T096); the limits are the PR check's own.
"""

from __future__ import annotations

from gcattr.diff import added_from_blobs, added_from_patch

__all__ = ["MAX_ADDED_LINES", "MAX_BLOB_BYTES", "added_from_blobs", "added_from_patch"]

MAX_ADDED_LINES = 5_000  # per file; above this the file is excluded as too_large
MAX_BLOB_BYTES = 2 * 1024 * 1024
