"""Options for the cluster-level suites (tests/e2e, tests/privacy), which run against a demo install."""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("gca cluster")
    g.addoption(
        "--gateway",
        default=os.environ.get("GATEWAY", "both"),
        choices=["both", "agentgateway", "litellm"],
        help="gateway(s) the end-to-end test installs, in turn (default: both, for the parity check)",
    )
    g.addoption("--kube-context", default=os.environ.get("GCA_KUBE_CONTEXT", "kind-gca"))
    g.addoption("--namespace", default=os.environ.get("GCA_NAMESPACE", "gca"))
    g.addoption("--release", default=os.environ.get("GCA_RELEASE", "gca"))
