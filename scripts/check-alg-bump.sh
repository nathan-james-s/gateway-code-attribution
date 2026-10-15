#!/usr/bin/env bash
# T095: a golden corpus is frozen once it has been released (Constitution III, FR-032, FR-033).
#
# Fails when this change edits, adds to or deletes any file of a corpus that a release (a `v*` tag) contains
# (lib/tests/golden/alg-<n>/), unless alg <n> is being retired (its directory deleted and <n> no longer in
# SUPPORTED_ALGS). Before alg <n> is first released its corpus may still change: threshold calibration (T109, T113)
# is allowed until then and regenerates it. A new corpus directory must be for the new ALG, and ALG must go up in
# the same change; the exception is the first corpus for the current ALG when the base has none for it.
#
#   scripts/check-alg-bump.sh [BASE_REF]      (default: origin/main)
set -euo pipefail
cd "$(dirname "$0")/.."
BASE_REF=${1:-origin/main}
BASE=$(git merge-base "$BASE_REF" HEAD)
ALGO=lib/src/gcattr/algorithm.py

alg_at() {  # alg_at <rev|WORKTREE> -> "ALG SUPPORTED..."
  local src
  if [ "$1" = WORKTREE ]; then src=$(cat "$ALGO"); else src=$(git show "$1:$ALGO" 2>/dev/null || true); fi
  python3 - "$src" <<'PY'
import re, sys
src = sys.argv[1]
if not src:  # the base predates the library
    print(0)
    raise SystemExit
alg = re.search(r"^ALG\s*=\s*(\d+)", src, re.M).group(1)
sup = re.search(r"^SUPPORTED_ALGS[^=]*=\s*\(([^)]*)\)", src, re.M).group(1)
print(alg, " ".join(x.strip() for x in sup.split(",") if x.strip()))
PY
}

read -r BASE_ALG _ <<<"$(alg_at "$BASE")"
read -r HEAD_ALG HEAD_SUPPORTED <<<"$(alg_at WORKTREE)"
fail=0
reported=" "
explain() {  # explain <corpus dir> <message>: once per corpus directory
  [[ "$reported" == *" $1 "* ]] && return
  reported="$reported$1 "
  echo "::error::$2"
  echo "  Golden outputs for an algorithm version never change (Constitution III; FR-032). A change that alters"
  echo "  fingerprints or outcomes must raise ALG in $ALGO and add lib/tests/golden/alg-<new ALG>/ with"
  echo "  'uv run python -m lib.tests.golden.generate', leaving every existing corpus untouched."
  fail=1
}

released() {  # released <n>: does any release tag contain the alg-<n> corpus?
  local tag
  for tag in $(git tag -l 'v*'); do
    git cat-file -e "$tag:lib/tests/golden/alg-$1" 2>/dev/null && return 0
  done
  return 1
}

while IFS=$'\t' read -r status path rest; do
  [ -z "${status:-}" ] && continue
  for p in "$path" ${rest:-}; do
    [[ "$p" =~ ^lib/tests/golden/alg-([0-9]+)/ ]] || continue
    n=${BASH_REMATCH[1]}
    if released "$n"; then
      if [[ "$status" == D* ]] && [ ! -d "lib/tests/golden/alg-$n" ] && [[ " $HEAD_SUPPORTED " != *" $n "* ]]; then
        continue  # alg n retired: its whole corpus goes with it
      fi
      explain "alg-$n" "the alg-$n golden corpus changed ($status $p), and alg $n has been released."
    elif git cat-file -e "$BASE:lib/tests/golden/alg-$n" 2>/dev/null; then
      continue  # alg n hasn't been released yet: its corpus may still change (T109, T113)
    elif [ "$n" = "$HEAD_ALG" ] && { [ "$HEAD_ALG" -gt "$BASE_ALG" ] || [ "$n" = "$BASE_ALG" ]; }; then
      continue  # the corpus for a new ALG, or the first corpus for the current one
    else
      explain "alg-$n" "a new corpus alg-$n doesn't match ALG $HEAD_ALG (base ALG $BASE_ALG)."
    fi
  done
done < <(git diff --name-status -M "$BASE" -- lib/tests/golden/)

if [ "$HEAD_ALG" -gt "$BASE_ALG" ] && [ ! -d "lib/tests/golden/alg-$HEAD_ALG" ]; then
  explain "alg-$HEAD_ALG" "ALG went from $BASE_ALG to $HEAD_ALG without a lib/tests/golden/alg-$HEAD_ALG corpus."
fi
[ "$fail" = 0 ] && echo "golden corpus check passed (ALG $HEAD_ALG; supported: $HEAD_SUPPORTED)"
exit "$fail"
