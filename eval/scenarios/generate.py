"""Write the published scenario set (T101-T105) from the definitions below.

    uv run python eval/scenarios/generate.py            # every scenario except the formatter ones
    uv run python eval/scenarios/generate.py --formatters   # also formatters-* (needs uv and Docker)

Every expected label comes from how the scenario is written (gca_eval.author): what the model wrote, what a
person typed or changed. Synthetic code only, except the corpus-* scenarios: real responses recorded from a coding
tool doing the synthetic tasks in eval/corpus/tasks.md, with the owner's consent (T112).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gca_eval.author import Builder, Doc, formatted_doc, patch_call, token_key, write_call
from gca_eval.corpus import recorded, replay, written_lines

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------------------------- seed (T101)
def seed_line_accuracy() -> Builder:
    """Spec 002's line-accuracy categories: unmodified, edited, typed and trivial lines, across API formats."""
    b = Builder(
        "seed-line-accuracy", "seed", "Unmodified, edited, typed and trivial lines across four API formats."
    )
    ada = b.author("ada")
    pricing = (
        Doc("src/pricing.py")
        .ai("from dataclasses import dataclass", "", "", "@dataclass(frozen=True)", "class LineItem:")
        .ai("    sku: str", "    unit_price_cents: int", "    quantity: int", "", "")
        .ai(
            "def subtotal_cents(items):",
            "    return sum(i.unit_price_cents * i.quantity for i in items)",
            "",
            "",
        )
        .ai("def apply_discount(total_cents, percent):", "    if not 0 <= percent <= 100:")
        .edit(
            '        raise ValueError("discount must be between 0 and 100")',
            '        raise ValueError(f"discount must be between 0 and 100, got {percent}")',
            tier="anchored",
        )
        .ai("    return total_cents - total_cents * percent // 100", "", "")
        .edit(
            "def tax_cents(total_cents, rate=0.08):",
            "def tax_cents(total_cents, rate=0.0825):",
            tier="anchored",
        )
        .ai("    return round(total_cents * rate)", "", "")
        .human("def format_cents(cents):", '    return f"${cents / 100:,.2f}"')
    )
    inventory = (
        Doc("src/inventory.py")
        .ai("class OutOfStock(Exception):", "    pass", "", "")
        .ai(
            "def reserve(stock, sku, quantity):",
            "    available = stock.get(sku, 0)",
            "    if available < quantity:",
        )
        .ai('        raise OutOfStock(f"{sku}: {available} left, {quantity} requested")')
        .ai("    stock[sku] = available - quantity", "    return stock[sku]", "", "")
        .ai("def restock(stock, sku, quantity):")
        .edit(
            "    stock[sku] = stock.get(sku, 0) + quantity",
            "    stock[sku] = stock.get(sku, 0) + max(quantity, 0)",
            tier="anchored",
        )
        .ai("    return stock[sku]")
        .human("", "", "def low_stock(stock, threshold=5):")
        .human("    return sorted(sku for sku, count in stock.items() if count <= threshold)")
    )
    receipts = (
        Doc("src/receipts.ts")
        .ai(
            "export interface ReceiptLine {",
            "  sku: string;",
            "  quantity: number;",
            "  totalCents: number;",
            "}",
        )
        .ai("", "export function receiptTotal(lines: ReceiptLine[]): number {")
        .ai("  return lines.reduce((sum, line) => sum + line.totalCents, 0);", "}", "")
        .human("// Lines with a zero quantity are refunds and don't count as items.")
        .human("export function receiptCount(lines: ReceiptLine[]): number {")
        .human("  return lines.filter((line) => line.quantity > 0).length;", "}")
    )
    b.write_docs(ada, "anthropic_messages", [pricing])
    b.write_docs(ada, "openai_chat", [inventory])
    b.write_docs(ada, "gemini_native", [receipts])
    b.branch("feature")
    for d in (pricing, inventory, receipts):
        b.commit(ada, {d.path: d.final_text()})
        b.expect(d)
    b.note(file="src/pricing.py", edits=["error message gains the value", "tax default 0.08 -> 0.0825"])
    b.note(
        file="src/inventory.py",
        edits=["restock guards against negative quantities", "low_stock typed by hand"],
    )
    return b


def _rewrite_docs(prefix: str) -> list[Doc]:
    orders = (
        Doc(f"src/{prefix}_orders.py")
        .ai("def order_total(order):", "    lines = order.get('lines', [])")
        .ai("    gross = sum(line['price'] * line['qty'] for line in lines)")
        .ai("    discount = order.get('discount_cents', 0)", "    return max(gross - discount, 0)", "", "")
        .ai("def is_paid(order):", "    return order.get('status') in ('paid', 'refunded')")
    )
    shipping = (
        Doc(f"src/{prefix}_shipping.py")
        .ai("RATES = {'standard': 499, 'express': 1299, 'overnight': 2499}", "", "")
        .ai("def shipping_cents(method, weight_kg):", "    base = RATES[method]")
        .ai("    surcharge = max(0, round((weight_kg - 2) * 150))", "    return base + surcharge")
    )
    return [orders, shipping]


def seed_rewrite_rebase() -> Builder:
    """Spec 002's history rewrite: the PR is rebased onto a base that moved. Agent lines keep their attribution."""
    b = Builder("seed-rewrite-rebase", "seed", "Agent commits rebased onto a moved base (SC-004).")
    ada = b.author("ada")
    orders, shipping = _rewrite_docs("rebase")
    b.write_docs(ada, "openai_responses", [orders, shipping])
    b.commit("base", {"README.md": "# shop\n"}, branch="main", message="base")
    b.branch("feature")
    b.commit(ada, {orders.path: orders.final_text()})
    b.commit(ada, {shipping.path: shipping.final_text()})
    b.commit(
        "base", {"README.md": "# shop\n\nNow with orders.\n", "CHANGELOG.md": "- base moved\n"}, branch="main"
    )
    b.op(op="rebase", branch="feature", onto="main", author=ada)
    for d in (orders, shipping):
        b.expect(d, tags=("rewrite",))
    return b


def seed_rewrite_squash() -> Builder:
    """Spec 002's history rewrite: `merge --squash` into a new branch. Agent lines keep their attribution."""
    b = Builder("seed-rewrite-squash", "seed", "Three agent commits squashed into one (SC-004).")
    ada = b.author("ada")
    orders, shipping = _rewrite_docs("squash")
    b.write_docs(ada, "anthropic_messages", [orders])
    b.write_docs(ada, "openai_chat", [shipping])
    b.commit("base", {"README.md": "# shop\n"}, branch="main", message="base")
    b.branch("work")
    b.commit(ada, {orders.path: orders.final_text()}, branch="work")
    b.commit(ada, {shipping.path: shipping.final_text()}, branch="work")
    b.op(
        op="squash",
        **{"from": "work"},
        into="feature",
        base="main",
        author=ada,
        message="orders and shipping",
    )
    for d in (orders, shipping):
        b.expect(d, tags=("rewrite",))
    return b


# ---------------------------------------------------------------------------------------------- human edits (T102)
def human_edits_tokens() -> Builder:
    """Single-token edits, renamed identifiers, added arguments, edited strings, deleted-then-retyped lines.
    Same-file exact anchors exist, so edits are expected through the anchored tier."""
    b = Builder("human-edits-tokens", "human-edits", "Small human edits to AI lines, with same-file anchors.")
    ada = b.author("ada")
    users = (
        Doc("app/users.py")
        .ai("import re", "", "EMAIL = re.compile(r'^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$')", "", "")
        .ai("def normalize_email(address):", "    cleaned = address.strip().lower()")
        .edit("    if not EMAIL.match(cleaned):", "    if not EMAIL.fullmatch(cleaned):", tier="anchored")
        .edit(
            "        raise ValueError('invalid email address')",
            "        raise ValueError(f'invalid email address: {address!r}')",
            tier="anchored",
        )
        .ai("    return cleaned", "", "")
        .edit(
            "def display_name(first, last):", "def display_name(first, last, middle=None):", tier="anchored"
        )
        .edit("    parts = [first, last]", "    parts = [first, middle, last]", tier="anchored")
        .ai("    return ' '.join(p for p in parts if p)", "", "")
        .ai("def username_for(first, last, taken):")
        .edit("    base = (first[0] + last).lower()", "    stem = (first[0] + last).lower()", tier="anchored")
        .edit("    candidate, n = base, 1", "    candidate, n = stem, 1", tier="anchored")
        .ai("    while candidate in taken:", "        n += 1")
        .edit("        candidate = f'{base}{n}'", "        candidate = f'{stem}{n}'", tier="anchored")
        .ai("    return candidate")
        .human("", "", "def is_admin(user):", "    return 'admin' in user.get('roles', ())")
    )
    retyped = Doc("app/flags.py").ai("FEATURES = {'beta_search': False, 'new_checkout': True}", "", "")
    retyped.ai("def enabled(name):").ai("    return FEATURES.get(name, False)", tags=("retyped",))
    b.write_docs(ada, "anthropic_messages", [users, retyped])
    # Unapplied output: the model also wrote a module nobody committed. It must not raise the AI share.
    unused = Doc("app/unused_audit.py").ai(
        "def audit(event):", "    print('AUDIT', event['type'], event['user'])"
    )
    b.write_docs(ada, "anthropic_messages", [unused])
    b.branch("feature")
    b.commit(ada, {users.path: users.final_text(), retyped.path: retyped.final_text()})
    b.expect(users)
    b.expect(retyped)
    b.note(unapplied="app/unused_audit.py was generated and never committed")
    return b


def human_edits_moved() -> Builder:
    """Edited lines moved to another file have no same-file anchor: broad tier. A file at a captured path but with
    no exact line left is a path-only case: broad or human, never anchored."""
    b = Builder("human-edits-moved", "human-edits", "Edited lines in other files; path-only matches.")
    ada = b.author("ada")
    model_util = (
        Doc("lib/util.py")
        .ai(
            "def chunked(items, size):",
            "    return [items[i:i + size] for i in range(0, len(items), size)]",
            "",
            "",
        )
        .ai(
            "def dedupe(items):",
            "    seen = set()",
            "    return [x for x in items if not (x in seen or seen.add(x))]",
        )
    )
    b.write_docs(ada, "openai_chat", [model_util])
    moved = (
        Doc("lib/batching.py")
        .edit(
            "    return [items[i:i + size] for i in range(0, len(items), size)]",
            "    return [items[i:i + size] for i in range(0, len(items), size or 1)]",
            tier="broad",
        )
        .edit(
            "    return [x for x in items if not (x in seen or seen.add(x))]",
            "    return [x for x in items if not (x in seen or seen.add(x))][:limit]",
            tier="broad",
        )
        .human("def first(items):", "    return items[0] if items else None")
    )
    # Path-only: the model wrote lib/util.py; the committed lib/util.py keeps none of its lines exactly.
    path_only = (
        Doc("lib/util.py")
        .edit("def chunked(items, size):", "def chunked(items, size=100):", tier="broad", tags=("path_only",))
        .edit("def dedupe(items):", "def dedupe(items, key=None):", tier="broad", tags=("path_only",))
        .human(
            "    keyed = items if key is None else map(key, items)", "    return list(dict.fromkeys(keyed))"
        )
    )
    b.branch("feature")
    b.commit(ada, {moved.path: moved.final_text(), path_only.path: path_only.final_text()})
    b.expect(moved)
    b.expect(path_only)
    return b


# ---------------------------------------------------------------------------------------------- formatters (T103)
PY_UNFORMATTED = """\
import json
def load_config(path,defaults=None):
    defaults=defaults or {}
    with open(path,encoding='utf-8') as fh:
        data=json.load(fh)
    merged={**defaults,**data}
    missing=[key for key in ('name','version','entrypoint') if key not in merged]
    if missing: raise KeyError('missing config keys: '+', '.join(missing))
    return merged
def summarize(config):
    return {'name':config['name'],'version':config['version'],'plugins':len(config.get('plugins',[])),'debug':bool(config.get('debug'))}
"""

TS_UNFORMATTED = """\
export type Plugin = { name: string, enabled: boolean, priority?: number }
export function activePlugins(plugins: Plugin[]): Plugin[] {
  return plugins.filter(p => p.enabled).sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
}
export function pluginNames(plugins: Plugin[]): string {
  return activePlugins(plugins).map(p => p.name).join(", ")
}
export const DEFAULT_PLUGINS: Plugin[] = [{ name: 'auth', enabled: true, priority: 10 }, { name: 'audit', enabled: false }]
"""

GO_UNFORMATTED = """\
package config

import "strings"

type Plugin struct {
Name string
Enabled bool
Priority int
}

func ActiveNames(plugins []Plugin) string {
names := []string{}
for _, p := range plugins { if p.Enabled { names = append(names, p.Name) } }
return strings.Join(names, ", ")
}
"""


def formatters(name: str, path: str, model_text: str, formatter: str, api_format: str) -> Builder:
    b = Builder(name, "formatters", f"AI output passed through {formatter} before committing (SC-003).")
    ada = b.author("ada")
    doc, note = formatted_doc(path, model_text, formatter)
    b.stream(ada, api_format, [write_call(path, api_format, 1, content=model_text)])
    b.branch("feature")
    b.commit(ada, {path: doc.final_text()})
    b.expect(doc)
    b.note(file=path, **note)
    return b


# ---------------------------------------------------------------------------------------------- lookalike, refactor (T104)
def lookalike() -> Builder:
    """Human code that looks like typical AI output, with no matching capture: the false AI modified rate."""
    b = Builder("lookalike-helpers", "lookalike", "Human-written helpers resembling common AI output.")
    ada = b.author("ada")
    captured = (
        Doc("svc/retry.py")
        .ai(
            "import time",
            "",
            "",
            "def retry(fn, attempts=3, delay=0.5):",
            "    for attempt in range(attempts):",
        )
        .ai("        try:", "            return fn()", "        except Exception:")
        .ai(
            "            if attempt == attempts - 1:",
            "                raise",
            "            time.sleep(delay * 2 ** attempt)",
        )
    )
    b.write_docs(ada, "anthropic_messages", [captured])
    human = Doc("svc/backoff.py").human(
        "import random",
        "",
        "",
        "def jittered_backoff(base, attempt, cap=30.0):",
        "    ceiling = min(cap, base * 2 ** attempt)",
        "    return random.uniform(0, ceiling)",
        "",
        "",
        "def with_timeout(fn, seconds):",
        "    deadline = time.monotonic() + seconds",
        "    result = fn()",
        "    if time.monotonic() > deadline:",
        "        raise TimeoutError(f'took longer than {seconds}s')",
        "    return result",
        "",
        "",
        "def call_with_retries(fn, tries=4, pause=0.25):",
        "    for n in range(tries):",
        "        try:",
        "            return fn(timeout=pause * 8)",
        "        except ConnectionError:",
        "            if n + 1 == tries:",
        "                raise",
        "            time.sleep(pause * (n + 1))",
        tags=("lookalike",),
    )
    b.branch("feature")
    b.commit(ada, {human.path: human.final_text()})
    b.expect(human)
    return b


def refactor() -> Builder:
    """The model writes a module; a person extracts part of it into a new file and renames things."""
    b = Builder("refactor-extract-rename", "refactor", "Renames and extractions across files.")
    ada = b.author("ada")
    model_report = (
        Doc("reports/sales.py")
        .ai("def monthly_totals(orders):", "    totals = {}", "    for order in orders:")
        .ai(
            "        month = order['created'][:7]",
            "        totals[month] = totals.get(month, 0) + order['total']",
        )
        .ai("    return dict(sorted(totals.items()))", "", "")
        .ai(
            "def best_month(orders):",
            "    totals = monthly_totals(orders)",
            "    return max(totals, key=totals.get)",
        )
    )
    b.write_docs(ada, "gemini_native", [model_report])
    kept = (
        Doc("reports/sales.py")
        .human("from reports.periods import totals_by_month", "", "")  # the import is new
        .edit("def best_month(orders):", "def busiest_month(orders):", tier="anchored")
        .edit("    totals = monthly_totals(orders)", "    totals = totals_by_month(orders)", tier="anchored")
        .ai("    return max(totals, key=totals.get)")
    )
    extracted = (
        Doc("reports/periods.py")
        .edit("def monthly_totals(orders):", "def totals_by_month(orders):", tier="broad")
        .ai("    totals = {}", "    for order in orders:")
        .ai(
            "        month = order['created'][:7]",
            "        totals[month] = totals.get(month, 0) + order['total']",
        )
        .ai("    return dict(sorted(totals.items()))")
    )
    b.branch("feature")
    b.commit(ada, {kept.path: kept.final_text(), extracted.path: extracted.final_text()})
    b.expect(kept)
    b.expect(extracted)
    return b


# ---------------------------------------------------------------------------------------------- multi-author, faults, rotation, empty (T105)
def multi_author() -> Builder:
    """Two developers with gateway credentials, one without captures, and an author GitHub can't link."""
    b = Builder("multi-author-pr", "multi-author", "Several authors in one PR: lines are credited by blame.")
    ada, bea, carl = b.author("ada"), b.author("bea"), b.author("carl")
    ghost = b.author("ghost", unmapped=True)
    a = Doc("api/handlers.py").ai(
        "def get_user(db, user_id):", "    row = db.fetch_one('select * from users where id = ?', user_id)"
    )
    a.ai("    return dict(row) if row else None")
    c = Doc("api/serializers.py").ai(
        "def serialize_user(user):", "    return {'id': user['id'], 'email': user['email']}"
    )
    h = Doc("api/health.py").human("def health(db):", "    return {'db': db.ping(), 'version': VERSION}")
    g = Doc("api/legacy.py").human(
        "def legacy_lookup(db, email):",
        "    return db.fetch_one('select id from users where email = ?', email)",
    )
    b.write_docs(ada, "anthropic_messages", [a])
    b.write_docs(bea, "openai_chat", [c])
    b.write_docs(ada, "openai_chat", [Doc("api/serializers.py").ai("def serialize_user(user):",
                 "    return {'id': user['id'], 'email': user['email']}")])  # ada has the same code: credit decides  # fmt: skip
    b.branch("feature")
    b.commit(bea, {c.path: c.final_text()})
    b.commit(ada, {a.path: a.final_text()})
    b.commit(carl, {h.path: h.final_text()})
    b.commit(ghost, {g.path: g.final_text()})
    for d in (a, c, h):
        b.expect(d)
    b.expect(g, unmapped=True)
    return b


def faults() -> Builder:
    """Broken streams and a lost capture message: each must be reported as loss, none silently dropped."""
    b = Builder(
        "faults-streams", "faults", "Truncated and schema-deviant streams, and a dropped capture message."
    )
    ada = b.author("ada")
    good = Doc("jobs/cleanup.py").ai(
        "def expired(sessions, now):", "    return [s for s in sessions if s['expires_at'] < now]"
    )
    b.stream(ada, "openai_chat", [write_call(Doc("jobs/lost.py").ai("def lost_work(queue):",
             "    return [item for item in queue if item.get('retries', 0) > 3]"), "openai_chat", 1)], fault="dropped")  # fmt: skip
    b.stream(ada, "anthropic_messages", [], fault="truncated")
    b.stream(ada, "openai_responses", [], fault="unexpected_format")
    b.write_docs(ada, "anthropic_messages", [good])
    b.branch("feature")
    b.commit(ada, {good.path: good.final_text()})
    b.expect(good)
    b.loss.update({"truncated": 1, "unexpected_format": 1, "seq_gap": 1})
    return b


def key_rotation() -> Builder:
    """Output captured under key generation 1, then a rotation, then more output: the PR still matches both."""
    b = Builder(
        "key-rotation-pr", "key-rotation", "Captures from before and after a fingerprint key rotation."
    )
    ada = b.author("ada")
    before = Doc("billing/invoice.py").ai(
        "def invoice_number(year, sequence):", "    return f'INV-{year}-{sequence:06d}'"
    )
    after = Doc("billing/credit.py").ai(
        "def credit_note_number(year, sequence):", "    return f'CN-{year}-{sequence:06d}'"
    )
    b.write_docs(ada, "anthropic_messages", [before], key_gen=1)
    b.write_docs(ada, "anthropic_messages", [after], key_gen=2)
    b.branch("feature")
    b.commit(ada, {before.path: before.final_text(), after.path: after.final_text()})
    b.expect(before)
    b.expect(after)
    return b


def empty_deletion() -> Builder:
    b = Builder("empty-deletion-only", "empty", "A PR that only deletes lines: nothing attributable, not 0%.")
    ada = b.author("ada")
    b.commit("base", {"src/old.py": "def old():\n    return 'old'\n\n\ndef older():\n    return 'older'\n"},
             branch="main", message="base")  # fmt: skip
    b.branch("feature")
    b.commit(ada, {"src/old.py": "def old():\n    return 'old'\n"})
    b.attributable = False
    return b


def empty_excluded() -> Builder:
    b = Builder(
        "empty-excluded-only", "empty", "A PR that only touches excluded files: nothing attributable."
    )
    ada = b.author("ada")
    b.write_docs(
        ada,
        "openai_chat",
        [Doc("vendor/lib/thing.js").ai("module.exports = function thing(a, b) { return a + b; };")],
    )
    b.branch("feature")
    b.commit(ada, {"package-lock.json": '{"lockfileVersion": 3, "packages": {}}\n',
                   "vendor/lib/thing.js": "module.exports = function thing(a, b) { return a + b; };\n"})  # fmt: skip
    b.attributable = False
    return b


def codex_patch() -> Builder:
    """Codex's freeform apply_patch (OpenAI Responses), with one human edit."""
    b = Builder("seed-codex-apply-patch", "seed", "A file added through Codex's freeform apply_patch.")
    ada = b.author("ada")
    doc = (
        Doc("cli/args.py")
        .ai("import argparse", "", "", "def parser():", "    p = argparse.ArgumentParser(prog='shop')")
        .ai("    p.add_argument('--verbose', action='store_true')")
        .edit(
            "    p.add_argument('--region', default='us')",
            "    p.add_argument('--region', default='us-east')",
            tier="anchored",
        )
        .ai("    return p")
    )
    b.stream(ada, "openai_responses", [patch_call(doc, 1)])
    b.branch("feature")
    b.commit(ada, {doc.path: doc.final_text()})
    b.expect(doc)
    return b


# ---------------------------------------------------------------------------------------------- corpus (T112)
def _recorded_doc(
    path: str, text: str, edits: dict[str, str], humans_after: dict[str, list[str]], written: set[str]
) -> Doc:
    """A file the model wrote (``text``), with a person's changes: ``edits`` (model line -> as changed) and lines
    typed after a given model line. Every other line is the model's. A changed or typed line must differ from
    every line the model wrote in the session (``written``): one that doesn't is AI unmodified by definition."""
    lines = text.splitlines()
    for key in (*edits, *humans_after):
        if lines.count(key) != 1:
            raise ValueError(f"{path}: {key!r} must name exactly one line")
    for typed in (*edits.values(), *(t for ts in humans_after.values() for t in ts)):
        if token_key(typed) in written:
            raise ValueError(f"{path}: {typed!r} equals a line the model wrote, so it isn't a person's line")
    doc = Doc(path)
    for ln in lines:
        if ln in edits:
            doc.edit(ln, edits[ln], tier="anchored")
        else:
            doc.ai(ln)
        if ln in humans_after:
            doc.human(*humans_after[ln])
    return doc


def corpus_claude_code() -> Builder:
    """Real Claude Code traffic (eval/corpus/claude-code): the five corpus tasks, every edit accepted, then a few
    changes by a person. The files are what replaying the recorded Write and Edit calls produces, which matched the
    owner's folder byte for byte when it was recorded."""
    b = Builder(
        "corpus-claude-code",
        "corpus",
        "Recorded Claude Code session (Write, Edit with replace_all, Bash, thinking blocks, an OpenRouter [DONE]"
        " trailer), then a few human edits.",
    )
    ada = b.author("ada")
    responses = recorded("claude-code")
    for r in responses:
        b.recorded(ada, r.api_format, r.data)
    files = replay(responses)
    written = written_lines(responses)
    raise_line = (
        '        raise ValueError(f"not enough stock for {sku}: requested {quantity}, available {available}")'
    )
    restock_line = "    stock[sku] = stock.get(sku, 0) + quantity"
    format_line = "  return usdFormatter.format(cents / 100);"
    docs = [
        _recorded_doc(
            "inventory.py",
            files["inventory.py"],
            {raise_line: raise_line.replace("not enough stock", "insufficient stock")},
            {restock_line: ['    audit_log.append(("restock", sku, quantity))']},
            written,
        ),
        _recorded_doc(
            "test_inventory.py",
            files["test_inventory.py"],
            {},
            {'            restock(stock, "apple", -3)': ["        self.assertEqual(len(stock), 1)"]},
            written,
        ),
        _recorded_doc(
            "prices.ts",
            files["prices.ts"],
            {format_line: format_line.replace("cents / 100", "Math.round(cents) / 100")},
            {},
            written,
        ),
        _recorded_doc("prices.test.ts", files["prices.test.ts"], {}, {}, written),
    ]
    b.branch("feature")
    b.commit(ada, {d.path: d.final_text() for d in docs})
    for d in docs:
        b.expect(d, tags=("corpus",))
    return b


SCENARIOS = [
    seed_line_accuracy,
    seed_rewrite_rebase,
    seed_rewrite_squash,
    codex_patch,
    human_edits_tokens,
    human_edits_moved,
    lookalike,
    refactor,
    multi_author,
    faults,
    key_rotation,
    empty_deletion,
    empty_excluded,
    corpus_claude_code,
]
FORMATTER_SCENARIOS = [
    ("formatters-python-black", "fmt/config.py", PY_UNFORMATTED, "black", "anthropic_messages"),
    ("formatters-typescript-prettier", "fmt/plugins.ts", TS_UNFORMATTED, "prettier", "openai_chat"),
    ("formatters-go-gofmt", "fmt/config.go", GO_UNFORMATTED, "gofmt", "gemini_native"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--formatters", action="store_true", help="also regenerate formatters-* (needs uv and Docker)"
    )
    args = ap.parse_args()
    total = 0
    for fn in SCENARIOS:
        b = fn()
        b.write(ROOT)
        total += len(b.expected)
        print(f"{b.name:32} {len(b.expected):3} labelled lines, {len(b.streams)} streams")
    if args.formatters:
        for spec in FORMATTER_SCENARIOS:
            b = formatters(*spec)
            b.write(ROOT)
            total += len(b.expected)
            print(f"{b.name:32} {len(b.expected):3} labelled lines")
    print(f"{total} labelled lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
