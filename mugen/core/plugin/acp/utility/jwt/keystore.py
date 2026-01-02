"""Provides a keystore abstraction for EdDSA (Ed25519 + Ed448) signing, verification,
and JWKS publishing.

Overview
--------
This module provides a minimal "keystore" abstraction for JWT signing and verification
using EdDSA with Ed25519 and Ed448 keys, and for publishing the corresponding public keys
as a JWKS document.

Primary goals:
- Support key rotation via a stable 'kid' in the JWT header.
- Strictly enforce algorithm constraints to prevent algorithm confusion attacks.
- Publish a JWKS containing *all* public keys required to validate outstanding tokens.

Design assumptions:
- Tokens are signed by the current service (or a trusted issuer service), using an
  asymmetric private key.
- Consumers verify signatures using public keys selected by 'kid' (either locally
  or via a JWKS endpoint exposed by the issuer).
- The service can store private keys securely (KMS/Vault/env secrets). JWKS only
  contains public keys.

Security notes:
- This module rejects tokens missing 'kid' or with an unexpected 'alg'.
- Do not mix HS256 and asymmetric algorithms without explicit routing and allowlists.
- Keep old public keys in JWKS until all tokens signed by them have expired
  (max(access_ttl, refresh_ttl) + buffer).

Compatibility notes:
- Ed25519 support is common; Ed448 support is less common across JWT middleware and API
  gateways. Validate end-to-end Ed448 compatibility before making an Ed448 key "active".
"""

import base64
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Union

import jwt
from jwt.exceptions import InvalidTokenError

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, ed448

# Type aliases for clarity
EdPrivateKey = Union[ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey]
EdPublicKey = Union[ed25519.Ed25519PublicKey, ed448.Ed448PublicKey]


def _b64url(data: bytes) -> str:
    """
    Base64url-encode bytes without padding (RFC 7515 / JWS / JWK conventions).

    Parameters
    ----------
    data:
        Raw bytes to encode.

    Returns
    -------
    str
        Base64url-encoded string without '=' padding.

    Notes
    -----
    JWK fields such as 'x' use unpadded base64url.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _crv_from_public_key(pub: EdPublicKey) -> str:
    """
    Map a cryptography EdDSA public key object to a JWK 'crv' name.

    Parameters
    ----------
    pub:
        An Ed25519PublicKey or Ed448PublicKey.

    Returns
    -------
    str
        "Ed25519" for Ed25519 keys, "Ed448" for Ed448 keys.

    Raises
    ------
    ValueError
        If an unsupported key type is provided.
    """
    if isinstance(pub, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(pub, ed448.Ed448PublicKey):
        return "Ed448"
    raise ValueError(f"Unsupported public key type: {type(pub)}")


def jwk_from_eddsa_public_key(pub: EdPublicKey, *, kid: str) -> Dict[str, Any]:
    """
    Convert an EdDSA public key (Ed25519 or Ed448) into a JWK suitable for JWKS.

    The JWK representation for EdDSA keys uses:
      - kty: "OKP" (Octet Key Pair)
      - crv: "Ed25519" or "Ed448"
      - x: base64url(raw public key bytes)

    Parameters
    ----------
    pub:
        The EdDSA public key (Ed25519 or Ed448) to serialize to JWK.
    kid:
        Key identifier to publish in the JWK. This must match the 'kid' included in
        the JWT header for tokens signed with the corresponding private key.

    Returns
    -------
    Dict[str, Any]
        A JWK dictionary containing the minimal required fields plus metadata fields:
        {"kty","crv","x","kid","use","alg"}.

    Raises
    ------
    ValueError
        If the public key type is unsupported.

    Notes
    -----
    - The returned JWK is public information and safe to publish.
    - "use":"sig" and "alg":"EdDSA" are included to help consumers filter keys.
    """
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "kty": "OKP",
        "crv": _crv_from_public_key(pub),  # "Ed25519" or "Ed448"
        "x": _b64url(raw),
        "kid": kid,
        "use": "sig",
        "alg": "EdDSA",
    }


@dataclass(frozen=True)
class EdDsaKeyEntry:
    """
    Container for an EdDSA keypair and its identifier.

    Attributes
    ----------
    kid:
        Key identifier used in JWT headers and JWKS entries.
    private_key:
        The private key used for signing JWTs (Ed25519 or Ed448).
    public_key:
        The public key used for verifying JWT signatures (Ed25519 or Ed448).

    Notes
    -----
    - Private keys must be kept secret and loaded from a secure source.
    - Public keys can be published as JWKS.
    """

    kid: str
    private_key: EdPrivateKey
    public_key: EdPublicKey


class EdDsaKeyStore:
    """
    In-memory keystore supporting EdDSA signing/verification with key rotation.

    The keystore holds multiple keys, indexed by 'kid', and designates one key as
    the active signing key. Verification selects the correct public key using the
    JWT header 'kid'.

    Parameters
    ----------
    keys:
        Iterable of EdDsaKeyEntry entries to load into the keystore.
    active_kid:
        The 'kid' corresponding to the key that should be used for signing new tokens.

    Raises
    ------
    ValueError
        If active_kid is not present in keys.

    Key rotation model
    ------------------
    - Add a new key entry (new kid) to the keystore.
    - Switch active_kid to the new key.
    - Continue publishing old public keys in JWKS until all tokens signed by them
      have expired (TTL + buffer), then remove them.

    Thread safety
    -------------
    This class is immutable after construction in the sense that it does not provide
    mutation APIs. If you want dynamic rotation without restart, build a new instance
    and swap a reference at a higher level.
    """

    def __init__(self, *, keys: Iterable[EdDsaKeyEntry], active_kid: str):
        keys_list = list(keys)

        # Fail fast on duplicate kids. Silent overwrite here can lead to verifying
        # against an unexpected key (last write wins), which is extremely difficult to
        # debug and can be security-relevant during rotation.
        seen = set()
        dupes = set()
        for k in keys_list:
            if k.kid in seen:
                dupes.add(k.kid)
            seen.add(k.kid)
        if dupes:
            raise ValueError(
                f"duplicate kid(s) in keystore: {', '.join(sorted(dupes))}"
            )

        self._keys: Dict[str, EdDsaKeyEntry] = {k.kid: k for k in keys_list}

        if active_kid not in self._keys:
            raise ValueError("active_kid not present in keys")

        self._active_kid = active_kid

    @property
    def active(self) -> EdDsaKeyEntry:
        """
        Return the active signing key entry.

        Returns
        -------
        EdDsaKeyEntry
            The key entry that should be used to sign new JWTs.
        """
        return self._keys[self._active_kid]

    def get_signing_key(self, kid: str) -> EdDsaKeyEntry:
        """
        Retrieve the signing key entry (includes private key material) for a given kid.

        This is intended for issuer-side token generation only.

        Parameters
        ----------
        kid:
            Key identifier to use for signing.

        Raises
        ------
        ValueError
            If kid is unknown.
        """
        entry = self._keys.get(kid)
        if not entry:
            raise ValueError("Unknown kid")
        return entry

    def get_public_key(self, kid: str) -> EdPublicKey:
        """
        Retrieve the public key for a given kid.

        Parameters
        ----------
        kid:
            Key identifier from the JWT header.

        Returns
        -------
        EdPublicKey
            The Ed25519 or Ed448 public key corresponding to kid.

        Raises
        ------
        jwt.exceptions.InvalidTokenError
            If kid is unknown. This is intentionally an InvalidTokenError so callers
            can treat it as an authentication failure without leaking detail.
        """
        entry = self._keys.get(kid)
        if not entry:
            raise InvalidTokenError("Unknown kid")
        return entry.public_key

    def jwks(self) -> Dict[str, Any]:
        """
        Build a JWKS payload for publication.

        Returns
        -------
        Dict[str, Any]
            A JWKS document of the form: {"keys": [<jwk1>, <jwk2>, ...]}.

        Notes
        -----
        Publish all keys that may be needed to verify currently-valid tokens, including:
        - the active key
        - any old keys that signed tokens that have not yet expired

        The JWKS returned here contains only public material and is safe to expose.
        """
        return {
            "keys": [
                jwk_from_eddsa_public_key(k.public_key, kid=k.kid)
                for k in self._keys.values()
            ]
        }


def load_eddsa_keystore_from_config(cfg: Any) -> EdDsaKeyStore:
    """
    Load an EdDsaKeyStore from an application configuration object.

    Expected config shape (example)
    -------------------------------
      cfg.acp.jwt.active_kid = "2025-12-ed1"
      cfg.acp.jwt.keys = [
        SimpleNamespace(kid="2025-12-ed1", alg="EdDSA", pem="-----BEGIN PRIVATE KEY-----..."}),
        SimpleNamespace(kid="2025-12-ed0", alg="EdDSA", pem="-----BEGIN PRIVATE KEY-----..."}),
      ]

    Parameters
    ----------
    cfg:
        A configuration object (often a SimpleNamespace-like structure) that exposes
        `cfg.acp.jwt.active_kid` and `cfg.acp.jwt.keys`.

    Returns
    -------
    EdDsaKeyStore
        A keystore containing all configured keys and the configured active key.

    Raises
    ------
    KeyError
        If required key fields are missing from the key dicts (e.g., 'kid', 'pem').
    ValueError
        If:
        - any key dict has alg != "EdDSA"
        - a private key is not Ed25519/Ed448
        - active_kid is not among the loaded keys
    TypeError
        If cfg does not have the expected attribute structure.

    Notes
    -----
    - Private keys are loaded from PEM in PKCS#8 format via cryptography.
    - Curve selection (Ed25519 vs Ed448) is inferred from the PEM key itself.
    - If you store encrypted private keys, you must pass a password to
      load_pem_private_key; this sketch assumes NoEncryption().
    """
    keys: list[EdDsaKeyEntry] = []
    for item in cfg.acp.jwt.keys:
        kid = item.kid
        alg = item.alg
        if alg != "EdDSA":
            raise ValueError(f"{kid}: unsupported alg for EdDSA keystore: {alg}")

        private_pem = item.pem.encode("utf-8")
        priv = serialization.load_pem_private_key(private_pem, password=None)

        if isinstance(priv, ed25519.Ed25519PrivateKey):
            keys.append(
                EdDsaKeyEntry(kid=kid, private_key=priv, public_key=priv.public_key())
            )
        elif isinstance(priv, ed448.Ed448PrivateKey):
            keys.append(
                EdDsaKeyEntry(kid=kid, private_key=priv, public_key=priv.public_key())
            )
        else:
            raise ValueError(f"{kid}: key is not Ed25519/Ed448")

    return EdDsaKeyStore(keys=keys, active_kid=cfg.acp.jwt.active_kid)


_FORBIDDEN_JWS_HEADERS = {
    # Protected / algorithm-safety and key selection
    "alg",
    "kid",
    # Critical extensions: do not allow unless you also enforce critical-header semantics
    "crit",
    # Prevent header-driven key material / indirection footguns for downstream consumers
    "jwk",
    "jku",
    "x5u",
    "x5c",
    "x5t",
    "x5t#s256",
}

_ALLOWED_JWS_HEADERS = {
    # Common, low-risk metadata headers
    "typ",
    "cty",
}


def _merge_jws_headers(
    base: Dict[str, Any],
    extra: Mapping[str, Any],
) -> Dict[str, Any]:
    merged = dict(base)
    for k, v in extra.items():
        if not isinstance(k, str) or not k.strip():
            raise ValueError("JWT header keys must be non-empty strings")
        kl = k.lower()
        if kl in _FORBIDDEN_JWS_HEADERS:
            raise ValueError(f"Refusing to set protected JWT header '{k}'")
        if kl in _ALLOWED_JWS_HEADERS or kl.startswith("x-"):
            # Canonicalize key casing to avoid duplicate keys like "typ" + "Typ".
            for existing in list(merged.keys()):
                if isinstance(existing, str) and existing.lower() == kl:
                    del merged[existing]
            merged[kl] = v
            continue
        raise ValueError(f"Unsupported JWT header '{k}'")
    return merged


def sign_eddsa_jwt(
    payload: dict,
    *,
    keystore: EdDsaKeyStore,
    kid: Optional[str] = None,
    extra_headers: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Sign a JWT using the active EdDSA key in the provided keystore.

    Parameters
    ----------
    payload:
        JWT claims/payload. Typically includes: sub/user_id, iat, exp, jti, type, etc.
    keystore:
        An EdDsaKeyStore with an active signing key.

    Returns
    -------
    str
        The compact-serialized JWT (JWS) string.

    Notes
    -----
    - Adds a JWT header with:
        - alg = "EdDSA"
        - kid = selected signing key (active unless kid override is provided)
        - typ = "JWT"
    - The token's cryptographic curve (Ed25519 vs Ed448) is determined by the active key.
    """
    k = keystore.active if kid is None else keystore.get_signing_key(kid)

    headers: Dict[str, Any] = {"kid": k.kid, "typ": "JWT"}
    if extra_headers:
        headers = _merge_jws_headers(headers, extra_headers)

    return jwt.encode(payload, k.private_key, algorithm="EdDSA", headers=headers)


def verify_eddsa_jwt(
    token: str,
    *,
    keystore: EdDsaKeyStore,
    verify_exp: bool = True,
    leeway_seconds: int = 0,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    required_claims: Optional[list[str]] = None,
) -> dict:
    """
    Verify an EdDSA-signed JWT using public keys from the keystore.

    This function is intentionally strict:
    - Requires header 'kid'
    - Requires header 'alg' == "EdDSA"
    - Selects the public key by 'kid'
    - Verifies signature, and optionally verifies exp/iss/aud

    Parameters
    ----------
    token:
        Compact JWT string from an Authorization header or cookie.
    keystore:
        EdDsaKeyStore containing public keys indexed by kid.
    verify_exp:
        Whether to enforce the 'exp' claim. Set False when you want to validate signature
        and parse claims even if expired (e.g., logout token revocation handling).
    issuer:
        If provided, enforce the 'iss' claim. If None, issuer is not checked.
    audience:
        If provided, enforce the 'aud' claim. If None, audience is not checked.

    Returns
    -------
    dict
        Decoded and verified JWT claims.

    Raises
    ------
    jwt.exceptions.ExpiredSignatureError
        If verify_exp is True and the token is expired.
    jwt.exceptions.InvalidTokenError
        If:
        - token is malformed
        - signature validation fails
        - kid is missing/unknown
        - alg is missing or not EdDSA
        - issuer/audience checks fail (when enabled)
        - other JWT validation checks fail

    Usage guidance
    --------------
    - Use verify_exp=True for normal request authentication.
    - Use verify_exp=False for workflows like logout where you still want to accept
      an expired token for cleanup/revocation, but only if signature is valid.
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    alg = header.get("alg")

    if not kid:
        raise InvalidTokenError("Missing kid")
    if alg != "EdDSA":
        raise InvalidTokenError("Invalid alg (expected EdDSA)")

    public_key = keystore.get_public_key(kid)

    # Require core claims to be present. Also validate iat/nbf if present.
    # Note: PyJWT validates exp/iat/nbf semantics when enabled; 'require' ensures presence.
    require_list = (
        required_claims if required_claims is not None else ["exp", "iat", "nbf"]
    )
    options = {
        "verify_exp": verify_exp,
        "verify_nbf": True,
        "verify_iat": True,
        "require": require_list,
    }

    return jwt.decode(
        token,
        public_key,
        algorithms=["EdDSA"],
        issuer=issuer,
        audience=audience,
        leeway=leeway_seconds,
        options=options,
    )
