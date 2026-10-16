"""`gca demo run` stops when the GitHub App isn't installed on the repo; `init-repo` prints the install link."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from gca_demo import agent

INSTALL = "https://github.com/apps/gca-demo-app/installations/new"


class FakeApp:
    def __init__(self, installed: bool) -> None:
        self.installed = installed
        self.asked: list[tuple[str, str]] = []

    async def app_slug(self) -> str:
        return "gca-demo-app"

    async def repo_installation(self, owner: str, repo: str) -> dict[str, Any] | None:
        self.asked.append((owner, repo))
        return {"id": 11} if self.installed else None


def _cli(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    agent.register(parser.add_subparsers(dest="command"))
    return parser.parse_args(list(argv))


def _write_secret(path: Path, fields: dict[str, str], key: str = "stringData") -> Path:
    if key == "data":
        fields = {k: base64.b64encode(v.encode()).decode() for k, v in fields.items()}
    path.write_text(yaml.safe_dump({"apiVersion": "v1", "kind": "Secret", key: fields}))
    return path


@pytest.mark.parametrize("key", ["stringData", "data"])
def test_load_app_reads_the_setup_secret(tmp_path: Path, key: str) -> None:
    secret = _write_secret(tmp_path / "s.yaml", {"appId": "123", "privateKey": "-----BEGIN KEY-----"}, key)
    app = agent.load_app(str(secret))
    assert app is not None and app.app_id == 123 and app.private_key == "-----BEGIN KEY-----"


def test_load_app_defaults_to_env_then_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GCA_GITHUB_APP_SECRET", raising=False)
    assert agent.load_app(None) is None
    _write_secret(tmp_path / agent.APP_SECRET, {"appId": "1", "privateKey": "k"})
    assert agent.load_app(None).app_id == 1  # type: ignore[union-attr]
    monkeypatch.setenv(
        "GCA_GITHUB_APP_SECRET",
        str(_write_secret(tmp_path / "other.yaml", {"appId": "2", "privateKey": "k"})),
    )
    assert agent.load_app(None).app_id == 2  # type: ignore[union-attr]


def test_load_app_without_id_or_key_is_none(tmp_path: Path) -> None:
    assert agent.load_app(str(_write_secret(tmp_path / "s.yaml", {"appId": "1"}))) is None
    assert agent.load_app(str(tmp_path / "missing.yaml")) is None
    (tmp_path / "bad.yaml").write_text("data:\n  appId: '%%% not base64'\n")
    assert agent.load_app(str(tmp_path / "bad.yaml")) is None
    (tmp_path / "list.yaml").write_text("- not a Secret\n")
    assert agent.load_app(str(tmp_path / "list.yaml")) is None


def test_missing_installation_fails_with_the_install_link() -> None:
    app = FakeApp(installed=False)
    with pytest.raises(agent.DemoError) as err:
        agent.check_installation(app, "octo/gca-sample")  # type: ignore[arg-type]
    assert app.asked == [("octo", "gca-sample")]
    assert "not installed on octo/gca-sample" in str(err.value)
    assert f"{INSTALL} and select octo/gca-sample" in str(err.value)


def test_installed_app_passes() -> None:
    agent.check_installation(FakeApp(installed=True), "octo/gca-sample")  # type: ignore[arg-type]


def test_no_credentials_warns_and_continues(capsys: pytest.CaptureFixture[str]) -> None:
    agent.check_installation(None, "octo/gca-sample")
    assert "warning: no GitHub App credentials" in capsys.readouterr().out


def test_run_stops_before_opening_a_pr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(agent, "load_app", lambda path: FakeApp(installed=False))

    def no_pr() -> tuple[str, str]:
        raise AssertionError("the demo went on to clone and open a PR")

    monkeypatch.setattr(agent, "_gh_identity", no_pr)
    args = _cli("demo", "run", "--repo", "octo/gca-sample", "--credential", "k")
    assert args.func(args) == 1
    out = capsys.readouterr().out
    assert out.startswith("error: the GitHub App gca-demo-app is not installed on octo/gca-sample")
    assert INSTALL in out


def _fake_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "_gh_identity", lambda: ("octo", "1+octo@users.noreply.github.com"))
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(agent, "_run", lambda cmd, cwd=None: " M README.md" if "status" in cmd else "")


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        (False, f"Install the GitHub App on it next: {INSTALL} and select octo/gca-sample"),
        (True, "The GitHub App gca-demo-app is already installed on it."),
    ],
)
def test_init_repo_prints_the_install_link(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], installed: bool, expected: str
) -> None:
    _fake_git(monkeypatch)
    monkeypatch.setattr(agent, "load_app", lambda path: FakeApp(installed))
    args = _cli("demo", "init-repo", "--repo", "octo/gca-sample")
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "Pushed the sample project to octo/gca-sample (main)." in out
    assert expected in out


def test_init_repo_without_credentials_still_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_git(monkeypatch)
    monkeypatch.setattr(agent, "load_app", lambda path: None)
    args = _cli("demo", "init-repo", "--repo", "octo/gca-sample")
    assert args.func(args) == 0
    assert "choose Install App and select octo/gca-sample" in capsys.readouterr().out
