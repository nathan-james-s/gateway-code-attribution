"""T053: added lines from compare patches, and from blobs when GitHub omits the patch."""

from __future__ import annotations

from gca_prcheck.diff import added_from_blobs, added_from_patch

PATCH = """@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = 3
 z = 4
\\ No newline at end of file
@@ -10,2 +11,3 @@ def f():
     a = 1
+    b = 2
     c = 3"""


def test_patch_line_numbers() -> None:
    assert added_from_patch(PATCH) == [(2, "x = 2"), (3, "y = 3"), (12, "    b = 2")]


def test_added_file_patch() -> None:
    assert added_from_patch("@@ -0,0 +1,2 @@\n+a\n+b") == [(1, "a"), (2, "b")]


def test_blobs() -> None:
    old = "a\nb\nc\n"
    new = "a\nB\nc\nd\n"
    assert added_from_blobs(old, new) == [(2, "B"), (4, "d")]
    assert added_from_blobs(None, "x\ny") == [(1, "x"), (2, "y")]
