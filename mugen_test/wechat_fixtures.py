"""Build signed encrypted WeChat envelopes with synthetic test credentials."""

import base64
import hashlib
import struct
from time import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AES_KEY = base64.b64encode(bytes(range(32))).decode().rstrip("=")


def encrypted_event(
    xml: str,
    *,
    token: str,
    aes_key: str = AES_KEY,
    timestamp: str | None = None,
    nonce: str = "test-nonce",
) -> tuple[bytes, dict[str, str]]:
    """Encode a provider-format event independently of the webhook verifier."""
    key = base64.b64decode(aes_key + "=")
    payload = xml.encode()
    plaintext = (
        b"0123456789ABCDEF"
        + struct.pack("!I", len(payload))
        + payload
        + b"test-app-id"
    )
    padding = 32 - len(plaintext) % 32
    plaintext += bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encrypted = base64.b64encode(
        encryptor.update(plaintext) + encryptor.finalize()
    ).decode()
    timestamp = str(int(time())) if timestamp is None else timestamp
    signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted])).encode()
    ).hexdigest()
    return (
        f"<xml><Encrypt>{encrypted}</Encrypt></xml>".encode(),
        {"timestamp": timestamp, "nonce": nonce, "msg_signature": signature},
    )
