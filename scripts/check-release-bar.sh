#!/usr/bin/env bash
# T110: the release bar is written in two places, the spec's SC-002/SC-003 (what we promise) and the release_bar
# constants in contracts/quality-report.schema.json (what `gca eval` enforces). Fail if they disagree (FR-044).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json, re, sys

spec = open("specs/001-gateway-code-attribution/spec.md").read()
bar = {k: v["const"] for k, v in json.load(open("specs/001-gateway-code-attribution/contracts/quality-report.schema.json"))
       ["properties"]["release_bar"]["properties"].items()}

def section(sc):
    m = re.search(rf"^- \*\*{sc}\*\*:(.*?)(?=^- \*\*SC-|\Z)", spec, re.S | re.M)
    if not m:
        sys.exit(f"release bar: {sc} not found in spec.md")
    return m.group(1)

def pct(text, pattern, what):
    m = re.search(pattern, text, re.S)
    if not m:
        sys.exit(f"release bar: couldn't read {what} from spec.md")
    return round(float(m.group(1)) / 100, 4)

sc2, sc3 = section("SC-002"), section("SC-003")
spec_bar = {
    "min_accuracy": pct(sc2, r"at least (\d+(?:\.\d+)?)%", "SC-002 accuracy"),
    "max_false_ai_modified_anchored": pct(sc3, r"at most (\d+(?:\.\d+)?)% for\s+anchored", "SC-003 anchored"),
    "max_false_ai_modified_broad": pct(sc3, r"at most (\d+(?:\.\d+)?)% for broad", "SC-003 broad"),
    "max_formatter_false_human": pct(sc3, r"formatter-caused.*?at most (\d+(?:\.\d+)?)%", "SC-003 formatter"),
}
diff = {k: (v, bar.get(k)) for k, v in spec_bar.items() if bar.get(k) != v}
if diff:
    for k, (s, c) in diff.items():
        print(f"::error::release bar {k}: spec.md says {s}, the schema's release_bar says {c}")
    sys.exit(1)
print("release bar: spec.md SC-002/SC-003 and the schema agree:", spec_bar, "max_silent_loss", bar["max_silent_loss"])
PY
