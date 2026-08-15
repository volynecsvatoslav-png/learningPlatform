import base64
import binascii
import json
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1,
    EllipticCurvePrivateKey,
)
from django.core.exceptions import ImproperlyConfigured

DEVELOPMENT_OFFLINE_LICENSE_PRIVATE_KEY_B64 = (
    "LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tCk1JR0hBZ0VBTUJNR0J5cUdTTTQ5QWdFR0NDcUdTTTQ5"
    "QXdFSEJHMHdhd0lCQVFRZ3RpRURSd2ZQMEtqN2dCVUkKYmRUSTMybS9XckVrWGEraXFERDhrbWQ5bm55"
    "aFJBTkNBQVNYYmpZWTB4QUJCSnI0WkpXMVIrVTU1THFiV1RNUQo2TDJoRUR6eHhUSG0vMGNQNGtoamt2"
    "QTQzK1hadWMxU2FBY0NMSkREb3BBS1IvS1R6cWVyNGRIcQotLS0tLUVORCBQUklWQVRFIEtFWS0tLS0tCg=="
)

DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "l242GNMQAQSa-GSVtUflOeS6m1kzEOi9oRA88cUx5v8",
    "y": "Rw_iSGOS8Djf5dm5zVJoBwIskMOikApH8pPOp6vh0eo",
}


def _normalized_jwk(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ImproperlyConfigured("VITE_OFFLINE_LICENSE_PUBLIC_JWK must be a JWK object")
    fields = {name: value.get(name) for name in ("kty", "crv", "x", "y")}
    if (
        fields["kty"] != "EC"
        or fields["crv"] != "P-256"
        or not isinstance(fields["x"], str)
        or not fields["x"]
        or not isinstance(fields["y"], str)
        or not fields["y"]
    ):
        raise ImproperlyConfigured(
            "VITE_OFFLINE_LICENSE_PUBLIC_JWK must contain an EC P-256 public key"
        )
    return {name: str(fields[name]) for name in ("kty", "crv", "x", "y")}


def validate_offline_license_keys(
    *, debug: bool, private_key_b64: str, public_jwk_json: str
) -> tuple[str, dict[str, str]]:
    private_value = private_key_b64.strip()
    if not private_value:
        if not debug:
            raise ImproperlyConfigured(
                "OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64 is required when DJANGO_DEBUG=false"
            )
        private_value = DEVELOPMENT_OFFLINE_LICENSE_PRIVATE_KEY_B64

    public_value: dict[str, str]
    if public_jwk_json.strip():
        try:
            public_value = _normalized_jwk(json.loads(public_jwk_json))
        except json.JSONDecodeError as error:
            raise ImproperlyConfigured(
                "VITE_OFFLINE_LICENSE_PUBLIC_JWK must be valid JSON"
            ) from error
    elif debug:
        public_value = DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK.copy()
    else:
        raise ImproperlyConfigured(
            "VITE_OFFLINE_LICENSE_PUBLIC_JWK is required when DJANGO_DEBUG=false"
        )

    try:
        private_key = serialization.load_pem_private_key(
            base64.b64decode(private_value, validate=True), password=None
        )
    except (ValueError, TypeError, binascii.Error) as error:
        raise ImproperlyConfigured(
            "OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64 must contain base64 PKCS8 PEM"
        ) from error
    if not isinstance(private_key, EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, SECP256R1
    ):
        raise ImproperlyConfigured("Offline license private key must use EC P-256")

    derived: dict[str, Any] = jwt.algorithms.ECAlgorithm.to_jwk(
        private_key.public_key(), as_dict=True
    )
    derived_public = _normalized_jwk(derived)
    if derived_public != public_value:
        raise ImproperlyConfigured(
            "OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64 does not match VITE_OFFLINE_LICENSE_PUBLIC_JWK"
        )
    if not debug and (
        private_value == DEVELOPMENT_OFFLINE_LICENSE_PRIVATE_KEY_B64
        or public_value == DEVELOPMENT_OFFLINE_LICENSE_PUBLIC_JWK
    ):
        raise ImproperlyConfigured(
            "Development offline license keys cannot be used when DJANGO_DEBUG=false"
        )
    return private_value, public_value
