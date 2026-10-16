"""An App with no installations is reported once per change, with the install link, not on every poll."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from gca_prcheck import polling


class Installations:
    def __init__(self, slug: str | None = "gca-demo-app") -> None:
        self.installations: list[dict[str, Any]] = []
        self.slug = slug

    async def list_installations(self) -> list[dict[str, Any]]:
        return self.installations

    async def installation_repositories(self, inst: int) -> list[dict[str, Any]]:
        return []

    async def app_slug(self) -> str:
        if self.slug is None:
            raise RuntimeError("GitHub is unreachable")
        return self.slug


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(polling, "_installation_count", None)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


async def test_no_installations_warns_once_with_install_link(caplog: pytest.LogCaptureFixture) -> None:
    gh = Installations()
    caplog.set_level(logging.INFO, logger="gca.prcheck.polling")
    for _ in range(3):
        assert await polling.poll_once(None, gh) == 0  # type: ignore[arg-type]
    assert _warnings(caplog) == [
        "GitHub App has no installations; install it on your repositories: "
        "https://github.com/apps/gca-demo-app/installations/new"
    ]


async def test_warns_again_only_after_the_count_changes(caplog: pytest.LogCaptureFixture) -> None:
    gh = Installations()
    caplog.set_level(logging.INFO, logger="gca.prcheck.polling")
    await polling.poll_once(None, gh)  # type: ignore[arg-type]
    gh.installations = [{"id": 11}]
    await polling.poll_once(None, gh)  # type: ignore[arg-type]
    await polling.poll_once(None, gh)  # type: ignore[arg-type]
    assert len(_warnings(caplog)) == 1
    assert "GitHub App has 1 installation" in caplog.text
    gh.installations = []
    await polling.poll_once(None, gh)  # type: ignore[arg-type]
    await polling.poll_once(None, gh)  # type: ignore[arg-type]
    assert len(_warnings(caplog)) == 2


async def test_warning_survives_a_failed_slug_lookup(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="gca.prcheck.polling")
    await polling.poll_once(None, Installations(slug=None))  # type: ignore[arg-type]
    [warning] = _warnings(caplog)
    assert warning.startswith("GitHub App has no installations; install it on your repositories: ")
    assert "Install App" in warning
