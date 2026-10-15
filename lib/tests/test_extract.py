"""T019: extraction of code lines from tool calls, patches, text blocks and truncated JSON."""

from __future__ import annotations

from gcattr import CapturedToolOutput, extract
from gcattr.extract import code_units, partial_string_fields
from gcattr.fingerprint import path_suffix_fps

from .conftest import TEST_KEY

CODE = "def total(items):\n    subtotal = sum(i.price for i in items)\n}\n    return round(subtotal, 2)\n"


def _out(
    payload: object, kind: str = "json_args", name: str = "Write", complete: bool = True
) -> CapturedToolOutput:
    return CapturedToolOutput("anthropic_messages", name, kind, payload, complete)  # type: ignore[arg-type]


def test_write_tool_lines_with_path_and_trivial_dropped() -> None:
    fps = extract(_out({"file_path": "/repo/src/app.py", "content": CODE}), TEST_KEY, 1)
    assert len(fps) == 3  # "}" is trivial
    assert fps[0].path_suffix_fps == path_suffix_fps("/repo/src/app.py", TEST_KEY, 1)
    assert [f.line_ordinal for f in fps] == [1, 2, 4]
    assert all(f.alg == 1 and f.key_gen == 1 for f in fps)


def test_edit_tool_excludes_old_string() -> None:
    units = code_units(
        _out({"file_path": "a.py", "old_string": "x = old(1, 2)", "new_string": "x = new(1, 2)"}, name="Edit")
    )
    assert units == [("a.py", "x = new(1, 2)", True)]


def test_multiedit_edits_list() -> None:
    units = code_units(
        _out(
            {
                "file_path": "a.py",
                "edits": [
                    {"old_string": "a = 1", "new_string": "a = compute(1)"},
                    {"old_string": "b = 2", "new_string": "b = compute(2)"},
                ],
            },
            name="MultiEdit",
        )
    )
    assert [u[1] for u in units] == ["a = compute(1)", "b = compute(2)"]


def test_unknown_string_fields_are_pathless_candidates() -> None:
    units = code_units(
        _out({"command": "cat > f.py <<'EOF'\nx = run(job)\nEOF", "description": "write a file"}, name="Bash")
    )
    assert units == [(None, "cat > f.py <<'EOF'\nx = run(job)\nEOF", True)]


def test_freeform_patch_takes_only_added_lines_and_header_path() -> None:
    patch = (
        "*** Begin Patch\n*** Update File: src/app.py\n@@ def total(items):\n"
        "-    return round(subtotal * 1.0825, 2)\n"
        "+    tax = rate_for(region)\n+    return round(subtotal * tax, 2)\n"
        "*** Add File: src/new.py\n+value = compute(a, b)\n*** End Patch\n"
    )
    units = code_units(_out(patch, kind="freeform", name="apply_patch"))
    assert units == [
        ("src/app.py", "    tax = rate_for(region)", True),
        ("src/app.py", "    return round(subtotal * tax, 2)", True),
        ("src/new.py", "value = compute(a, b)", True),
    ]


def test_text_block_fenced_code_only() -> None:
    text = "Here you go:\n```python\nresult = compute(a, b)\n```\nand prose."
    assert code_units(_out(text, kind="text_block", name=None)) == [(None, "result = compute(a, b)\n", True)]


def test_partial_string_fields_and_truncated_salvage() -> None:
    raw = '{"file_path": "/r/a.py", "content": "alpha = make(1)\\nbeta = make(2)\\ngam'
    fields, cut = partial_string_fields(raw)
    assert fields == {"file_path": "/r/a.py", "content": "alpha = make(1)\nbeta = make(2)\ngam"}
    assert cut == "content"
    fps = extract(_out(raw, complete=False), TEST_KEY, 1)
    assert len(fps) == 2  # the incomplete "gam" line is dropped


def test_partial_string_drops_incomplete_escape() -> None:
    fields, cut = partial_string_fields('{"content": "x = f(1)\\nend\\')
    assert cut == "content" and fields["content"] == "x = f(1)\nend"
