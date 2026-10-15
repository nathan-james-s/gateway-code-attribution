"""The App client keeps its githubkit clients alive (`.rest` holds only a weak reference) and can sign JWTs."""

from __future__ import annotations

import gc

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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
