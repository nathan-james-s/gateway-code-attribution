#!/usr/bin/env bash
# T113 (FR-045): docs/tools/supported.md may list a tool only if eval/corpus/<tool>/ has the owner's consent
# (consent.yaml with consent: true), its setup notes (setup.md, SC-011) and at least one recorded response.
# Conformance replays every recording through both gateways (tests/conformance), so a listed tool is also covered
# there.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import pathlib, re, sys

doc = pathlib.Path("docs/tools/supported.md").read_text()
tools = re.findall(r"^\|[^|]+\|\s*`([a-z0-9-]+)`\s*\|", doc, re.M)
problems = []
for tool in tools:
    d = pathlib.Path("eval/corpus") / tool
    consent = d / "consent.yaml"
    if not consent.is_file() or "consent: true" not in consent.read_text():
        problems.append(f"{tool}: no consent.yaml with consent: true")
    if not (d / "setup.md").is_file():
        problems.append(f"{tool}: no setup.md")
    if not list(d.glob("*/*.sse")):
        problems.append(f"{tool}: no recorded responses")
if problems:
    sys.exit("supported tools: " + "; ".join(problems))
print(f"supported tools: {', '.join(tools) or 'none'} listed, each with a consented corpus")
PY
