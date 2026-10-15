"""Versioned table of code-bearing tool-argument fields (research R7). Changing it requires a new ALG."""

from __future__ import annotations

TOOL_FIELDS_VERSION = "1"

# Fields whose string values are model-written code for the named path.
CODE_FIELDS: tuple[str, ...] = ("content", "new_string", "new_str", "patch", "code", "text", "file_text")
# Lists of edits whose items carry code, e.g. Claude Code MultiEdit {"edits": [{"old_string", "new_string"}]}.
EDIT_LIST_FIELDS: tuple[str, ...] = ("edits",)
EDIT_ITEM_CODE_FIELDS: tuple[str, ...] = ("new_string", "new_str", "content")
PATH_FIELDS: tuple[str, ...] = ("file_path", "path", "filename")

# String fields that are never model-written output code: existing code being replaced, search inputs,
# prose. Everything else that is a string becomes pathless candidate lines (rule 3).
EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        "old_string",
        "old_str",
        "description",
        "prompt",
        "query",
        "pattern",
        "glob",
        "url",
        "plan",
        "explanation",
        "reason",
        "subagent_type",
        "todos",
        "status",
        "id",
        "name",
        "language",
        "encoding",
        "mode",
    }
    | set(PATH_FIELDS)
)

PATCH_BEGIN = "*** Begin Patch"
