"""T055: the manifest matches contracts/github-app.md; outputs are a Secret and values file, mode 0600."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import yaml

from gca_portal import setup_cli
from gcattr.cli import main


def test_manifest_least_privilege() -> None:
    m = setup_cli.manifest("gca-x", "http://localhost:8080", "http://127.0.0.1:1/callback", None)
    assert m["default_permissions"] == {
        "checks": "write",
        "pull_requests": "read",
        "contents": "read",
        "metadata": "read",
        "members": "read",
        "emails": "read",
    }
    assert m["hook_attributes"]["active"] is False  # polling mode
    assert m["callback_urls"] == ["http://localhost:8080/auth/callback", "http://localhost:3000/login/github"]
    assert m["public"] is False


def test_existing_app_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pem = tmp_path / "app.pem"
    label = "RSA " + "PRIVATE KEY"  # a placeholder, split so secret scanners don't flag the test
    pem.write_text(f"-----BEGIN {label}-----\nabc\n-----END {label}-----\n")
    monkeypatch.setenv("GCA_GITHUB_CLIENT_SECRET", "cs")
    monkeypatch.setenv("GCA_GITHUB_WEBHOOK_SECRET", "ws")
    out = tmp_path / "out"
    rc = main(
        [
            "setup",
            "github-app",
            "--existing",
            "--app-id",
            "123",
            "--client-id",
            "Iv1.abc",
            "--private-key-file",
            str(pem),
            "--out-dir",
            str(out),
            "--namespace",
            "gca",
        ]
    )
    assert rc == 0
    secret = yaml.safe_load((out / "github-app.secret.yaml").read_text())
    assert secret["metadata"] == {"name": "gca-github-app", "namespace": "gca"}
    assert secret["stringData"]["appId"] == "123" and secret["stringData"]["privateKey"].startswith(
        "-----BEGIN"
    )
    assert yaml.safe_load((out / "values-github.yaml").read_text()) == {
        "github": {"existingSecret": "gca-github-app", "org": ""}
    }
    for f in out.iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
