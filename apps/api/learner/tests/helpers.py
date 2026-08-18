import base64
import uuid
from collections.abc import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as ec_utils
from django.test import Client
from rest_framework.response import Response


def make_device() -> tuple[uuid.UUID, dict[str, str], Callable[[bytes], str]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()

    def b64_int(value: int) -> str:
        return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode("ascii")

    public_key_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": b64_int(numbers.x),
        "y": b64_int(numbers.y),
    }

    def sign(message: bytes) -> str:
        der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
        r, s = ec_utils.decode_dss_signature(der)
        raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return uuid.uuid4(), public_key_jwk, sign


def request_exchange(
    client: Client,
    token: str,
    *,
    device: tuple[uuid.UUID, dict[str, str], Callable[[bytes], str]] | None = None,
    confirm_transfer: bool = False,
) -> Response:
    installation_id, public_key_jwk, sign = device or make_device()
    inspect = client.post(
        "/api/v1/auth/access/inspect",
        data={
            "token": token,
            "installation_id": str(installation_id),
            "public_key_jwk": public_key_jwk,
        },
        content_type="application/json",
    )
    assert inspect.status_code == 200, inspect.content
    challenge = inspect.json()["challenge"]
    return client.post(
        "/api/v1/auth/access/exchange",
        data={
            "token": token,
            "installation_id": str(installation_id),
            "public_key_jwk": public_key_jwk,
            "challenge": challenge,
            "signature": sign(challenge.encode("ascii")),
            "confirm_transfer": confirm_transfer,
        },
        content_type="application/json",
    )


def activate(
    client: Client,
    token: str,
    *,
    device: tuple[uuid.UUID, dict[str, str], Callable[[bytes], str]] | None = None,
    confirm_transfer: bool = False,
) -> tuple[uuid.UUID, dict[str, str], Callable[[bytes], str]]:
    installation_id, public_key_jwk, sign = device or make_device()
    response = request_exchange(
        client,
        token,
        device=(installation_id, public_key_jwk, sign),
        confirm_transfer=confirm_transfer,
    )
    assert response.status_code == 200, response.content
    return installation_id, public_key_jwk, sign
