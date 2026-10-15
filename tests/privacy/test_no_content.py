"""Privacy audit (T064; SC-006; Constitution II): after a demo run, no demo code is anywhere in the stack.

Runs against the demo cluster (kind by default). It needs a cluster where `gca demo run` has already been
attributed: the clean-install job runs it right after T065's end-to-end test, on the same cluster.
"""

from __future__ import annotations

import pytest

from .scan import Cluster, find, needles

pytestmark = pytest.mark.e2e


def _report(where: str, hits: list[str]) -> str:
    shown = "\n".join(f"  - {h[:80]}" for h in hits[:10])
    return f"{len(hits)} demo code line(s) found in {where}:\n{shown}"


@pytest.fixture(scope="module")
def needle_list() -> list[str]:
    return needles()


@pytest.fixture(scope="module")
def cluster(pytestconfig: pytest.Config) -> Cluster:
    c = Cluster(
        pytestconfig.getoption("--kube-context"),
        pytestconfig.getoption("--namespace"),
        pytestconfig.getoption("--release"),
    )
    try:
        c.kubectl("get", "pods")
    except Exception as exc:
        pytest.skip(f"no demo cluster reachable ({exc}); run `make demo` and `gca demo run` first")
    # The audit only means something after demo code has flowed through capture and the PR check.
    lines = int(c.psql("SELECT count(*) FROM captured_line") or 0)
    results = int(c.psql("SELECT count(*) FROM line_result") or 0)
    if not lines or not results:
        pytest.skip("no attributed demo run on this cluster yet: run `gca demo run` first")
    return c


def test_scanner_finds_a_planted_line(needle_list: list[str]) -> None:
    assert len(needle_list) > 50
    # Lines that only exist after a scripted human edit are needles too.
    assert "total = sum(item.price_cents * item.quantity * rate // 100 for item in eligible)" in needle_list
    assert "skus = sorted(sku for sku, count in self._stock.items() if count <= threshold)" in needle_list
    planted = needle_list[0]
    assert find(b"log: " + planted.encode(), needle_list) == [planted]
    assert find(b'{"x": "' + planted.replace('"', '\\"').encode() + b'"}', needle_list) == [planted]
    assert find(b"\\x" + planted.encode().hex().encode(), needle_list) == [planted]
    assert find(b"fingerprints only", needle_list) == []


def test_postgres_holds_no_code(cluster: Cluster, needle_list: list[str]) -> None:
    dump = cluster.kubectl(
        "exec", f"{cluster.fullname}-postgres-0", "--", "pg_dump", "-U", "gca", "-d", "gca", "--data-only"
    )
    assert len(dump) > 10_000  # a real dump, not an error page
    hits = find(dump, needle_list)
    assert not hits, _report("PostgreSQL (all schemas, all tables)", hits)


def test_jetstream_store_holds_no_code(cluster: Cluster, needle_list: list[str]) -> None:
    # The raw file store, so acknowledged-but-not-compacted messages are covered too.
    store = cluster.kubectl(
        "exec", f"{cluster.release}-nats-0", "-c", "nats", "--", "tar", "-cf", "-", "/data"
    )
    hits = find(store, needle_list)
    assert not hits, _report("the JetStream file store", hits)


def test_pod_logs_hold_no_code(cluster: Cluster, needle_list: list[str]) -> None:
    hits: dict[str, list[str]] = {}
    for pod, containers in cluster.pods():
        for container in containers:
            logs = cluster.kubectl("logs", pod, "-c", container, check=False)
            logs += cluster.kubectl("logs", pod, "-c", container, "--previous", check=False)
            if found := find(logs, needle_list):
                hits[f"{pod}/{container}"] = found
    assert not hits, "\n".join(_report(f"logs of {k}", v) for k, v in hits.items())


def test_grafana_database_holds_no_code(cluster: Cluster, needle_list: list[str]) -> None:
    db = cluster.kubectl(
        "exec",
        f"deploy/{cluster.release}-grafana",
        "-c",
        "grafana",
        "--",
        "cat",
        "/var/lib/grafana/grafana.db",
    )
    assert db.startswith(b"SQLite format 3")
    hits = find(db, needle_list)
    assert not hits, _report("Grafana's database", hits)


def test_litellm_spend_logs_hold_no_content(cluster: Cluster) -> None:
    has_litellm = cluster.psql(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'litellm' "
        "AND table_name = 'LiteLLM_SpendLogs'"
    ).strip()
    if has_litellm != "1":
        pytest.skip("this install has never run LiteLLM")
    rows = int(cluster.psql('SELECT count(*) FROM litellm."LiteLLM_SpendLogs"') or 0)
    # store_prompts_in_spend_logs: false keeps request and response bodies out of the spend log.
    with_content = cluster.psql(
        'SELECT count(*) FROM litellm."LiteLLM_SpendLogs" WHERE '
        "coalesce(messages::text, '') NOT IN ('', '{}', '[]', 'null', '\"\"') OR "
        "coalesce(response::text, '') NOT IN ('', '{}', '[]', 'null', '\"\"') OR "
        "coalesce(proxy_server_request::text, '') NOT IN ('', '{}', '[]', 'null', '\"\"')"
    ).strip()
    assert rows > 0, "LiteLLM ran but wrote no spend logs; the check would be vacuous"
    assert with_content == "0", (
        f"{with_content} of {rows} LiteLLM spend-log rows hold request or response content"
    )
