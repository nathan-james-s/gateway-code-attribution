"""Sign-in code exchange: exactly one request to GitHub; refusals become SignInError."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from gca_core.github import SignInError, exchange_code


async def test_single_request_with_redirect_uri() -> None:
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"access_token": "ghu_x", "token_type": "bearer"})

    user = await exchange_code(
        "cid",
        "secret",
        "code1",
        "http://localhost:8080/auth/callback",
        transport=httpx.MockTransport(handler),
    )
    assert user.token == "ghu_x" and len(calls) == 1
    form = parse_qs(calls[0].content.decode())
    assert form["code"] == ["code1"] and form["redirect_uri"] == ["http://localhost:8080/auth/callback"]


async def test_refused_code() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    with pytest.raises(SignInError, match="bad_verification_code"):
        await exchange_code("cid", "secret", "used", transport=httpx.MockTransport(handler))
