# Scripted coding tasks for the corpus

Small, synthetic tasks: cheap to run (about 5-10 model turns each) and between them they exercise every way a
tool writes code. Run each in a fresh, empty folder, in this order, and accept the tool's edits.

1. **New file.** "Create `inventory.py` with a function `reserve(stock, sku, quantity)` that subtracts from a
   dict of stock levels and raises `ValueError` when there isn't enough. Add a test file for it."
2. **Edit an existing file.** "In `inventory.py`, add a `restock(stock, sku, quantity)` function and make
   `reserve` reject non-positive quantities." (Exercises edit tools: Claude Code `Edit`, Codex `apply_patch`.)
3. **Several edits in one file.** "Rename `reserve` to `reserve_items` everywhere, and add type hints to every
   function." (Claude Code `MultiEdit`, or several patch hunks.)
4. **A second language.** "Create `prices.ts` exporting a function that formats cents as dollars, and a
   `prices.test.ts` for it."
5. **Ask and explain.** "Explain what `reserve_items` does, then add a docstring to it." (Code in prose and an
   edit in one session.)

Keep the folder: committing the result and opening a PR is how the corpus is checked end to end.
