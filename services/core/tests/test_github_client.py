"""The App client keeps its githubkit clients alive (`.rest` holds only a weak reference) and can sign JWTs.

It also tells "the App isn't installed on this repository" (404) apart from other GitHub errors.
"""

from __future__ import annotations

import gc

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from githubkit import AppAuthStrategy, GitHub
from githubkit.exception import RequestFailed

from gca_core.github import AppClient


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()


def test_app_client_survives_gc_and_signs_jwt() -> None:
    gh = AppClient(1, _pem())
    rest = gh._app().rest
    gc.collect()
    assert gh._app() is gh._app()
    assert rest.apps is not None  # would raise "client has already been collected" before the fix
    assert gh.installation(5) is gh.installation(5)
    flow = gh._app().auth.get_auth_flow(gh._app())
    assert flow._create_jwt().count(".") == 2  # needs githubkit[auth-app]


async def test_repo_installation_is_none_only_when_github_says_not_installed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        status = 404 if request.url.path == "/repos/octo/missing/installation" else 500
        return httpx.Response(status, json={"message": "Not Found" if status == 404 else "boom"})

    gh = AppClient(1, _pem())
    gh._app_gh = GitHub(
        AppAuthStrategy("1", gh.private_key), async_transport=httpx.MockTransport(handler), auto_retry=False
    )
    assert await gh.repo_installation("octo", "missing") is None
    with pytest.raises(RequestFailed):
        await gh.repo_installation("octo", "broken")
    assert seen[0] == "/repos/octo/missing/installation"
