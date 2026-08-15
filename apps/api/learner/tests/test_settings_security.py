import base64
import json
import os
import subprocess
import sys

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

from config.offline_keys import (
    DEVELOPMENT_OFFLINE_LICENSE_PRIVATE_KEY_B64,
    DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK,
)


def key_pair() -> tuple[str, str]:
    private_key = generate_private_key(SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return base64.b64encode(private_pem).decode("ascii"), json.dumps(public_jwk)


def import_production_settings(
    *, private_key: str | None, public_jwk: str | None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "settings-security-test-secret",
            "DATABASE_URL": "postgresql://learning:learning@localhost:5432/learning",
        }
    )
    for name, value in (
        ("OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64", private_key),
        ("VITE_OFFLINE_LICENSE_PUBLIC_JWK", public_jwk),
    ):
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=os.fspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_settings_require_private_offline_key() -> None:
    result = import_production_settings(private_key=None, public_jwk=None)
    assert result.returncode != 0
    assert "OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64 is required" in result.stderr


def test_production_settings_reject_development_offline_key() -> None:
    result = import_production_settings(
        private_key=DEVELOPMENT_OFFLINE_LICENSE_PRIVATE_KEY_B64,
        public_jwk=json.dumps(DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK),
    )
    assert result.returncode != 0
    assert "Development offline license keys cannot be used" in result.stderr


def test_production_settings_reject_mismatched_public_jwk() -> None:
    private_key, _ = key_pair()
    result = import_production_settings(
        private_key=private_key,
        public_jwk=json.dumps(DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK),
    )
    assert result.returncode != 0
    assert "does not match VITE_OFFLINE_LICENSE_PUBLIC_JWK" in result.stderr


def test_production_settings_accept_matching_custom_key_pair() -> None:
    private_key, public_jwk = key_pair()
    result = import_production_settings(private_key=private_key, public_jwk=public_jwk)
    assert result.returncode == 0, result.stderr
