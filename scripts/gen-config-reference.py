#!/usr/bin/env python3
"""Write docs/configuration.md, the Helm values reference, from the chart's values.schema.json (descriptions,
types, allowed values) and values.yaml (defaults) (T118). `--check` fails if the file is out of date or a setting
has no description, so the schema stays the one place values are documented.

    uv run python scripts/gen-config-reference.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "gateway-code-attribution"
OUT = ROOT / "docs" / "configuration.md"


def _type(node: dict[str, Any]) -> str:
    if "enum" in node:
        return " \\| ".join(f"`{v}`" for v in node["enum"])
    t = node.get("type", "")
    if t == "array" and isinstance(node.get("items"), dict):
        inner = _type(node["items"])
        return f"list of {inner}" if inner else "list"
    return t if isinstance(t, str) else " \\| ".join(t)


def _default(values: Any, path: list[str]) -> str:
    v = values
    for k in path:
        if not isinstance(v, dict) or k not in v:
            return ""
        v = v[k]
    if isinstance(v, dict):
        return ""
    if v == "" or v == [] or v is None:
        return "*(empty)*"
    text = json.dumps(v) if not isinstance(v, str) else v
    return f"`{text}`" if len(text) < 70 else f"`{text[:66]}…`"


def rows(node: dict[str, Any], values: Any, path: list[str], missing: list[str]) -> list[str]:
    out = []
    for key, child in (node.get("properties") or {}).items():
        p = [*path, key]
        name = ".".join(p)
        desc = child.get("description", "")
        if not desc:
            missing.append(name)
        has_children = bool(child.get("properties"))
        item_props = (
            (child.get("items") or {}).get("properties") if isinstance(child.get("items"), dict) else None
        )
        if not has_children or path:
            out.append(f"| `{name}` | {_type(child)} | {_default(values, p)} | {desc} |")
        if has_children:
            out += rows(child, values, p, missing)
        if item_props:
            out += rows(child["items"], {}, [*p[:-1], p[-1] + "[]"], missing)
    return out


def render() -> tuple[str, list[str]]:
    schema = json.loads((CHART / "values.schema.json").read_text())
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    missing: list[str] = []
    parts = [
        "# Configuration reference",
        "",
        "Every Helm value of the chart (`charts/gateway-code-attribution`), with its default. Generated from",
        "`values.schema.json` and `values.yaml` by `scripts/gen-config-reference.py`; edit those, not this file.",
        "Install and upgrade validate values against the schema. Secrets are always referenced by Secret name,",
        "never put in values.",
        "",
    ]
    for section, node in schema["properties"].items():
        parts += [f"## `{section}`", "", node.get("description", ""), ""]
        if not node.get("description"):
            missing.append(section)
        body = rows(node, values, [section], missing)
        if body:
            parts += ["| Key | Type | Default | Description |", "|---|---|---|---|", *body, ""]
    return "\n".join(parts).rstrip() + "\n", missing


def main(argv: list[str]) -> int:
    text, missing = render()
    if missing:
        print("values.schema.json: settings without a description: " + ", ".join(missing), file=sys.stderr)
        return 1
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(
                "docs/configuration.md is out of date: run scripts/gen-config-reference.py", file=sys.stderr
            )
            return 1
        print("docs/configuration.md is up to date")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
