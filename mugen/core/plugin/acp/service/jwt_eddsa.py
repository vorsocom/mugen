"""
Provides and implementation of IJwtService for EdDSA.
"""

import uuid
from typing import Any, Mapping, Optional

from jwt.exceptions import InvalidTokenError

from mugen.core import di
from mugen.core.plugin.acp.contract.service.jwt import (
    IJwtKeyStore,
    IJwtService,
    JwtSignParams,
    JwtVerifyParams,
    JwtVerifyProfile,
)
from mugen.core.plugin.acp.utility.jwt.keystore import (
    load_eddsa_keystore_from_config,
    sign_eddsa_jwt,
    verify_eddsa_jwt,
    EdDsaKeyStore,
)


class _EdDsaPublicKeyStore(IJwtKeyStore):
    """
    Public keystore view for EdDSA-backed JWT service.

    Wraps EdDsaKeyStore but only exposes safe/public operations.
    """

    def __init__(self, keystore: EdDsaKeyStore, active_kid: str):
        self._keystore = keystore
        self._active_kid = active_kid
        self._kids = {
            k.get("kid")
            for k in (keystore.jwks().get("keys", []) or [])
            if k.get("kid")
        }

    @property
    def active_kid(self) -> str:
        return self._active_kid

    def jwks(self) -> dict:
        return self._keystore.jwks()

    def has_kid(self, kid: str) -> bool:
        return kid in self._kids


def _require_claims_present(claims: dict, required: set[str]) -> None:
    missing = [k for k in required if (k not in claims) or (claims.get(k) is None)]
    if missing:
        raise InvalidTokenError(
            f"Invalid token: required claim(s) missing: {', '.join(sorted(missing))}."
        )


def _require_nonempty_str_claim(claims: dict, name: str) -> None:
    v = claims.get(name)
    if not isinstance(v, str) or not v.strip():
        raise InvalidTokenError(
            f"Invalid token: claim '{name}' must be a non-empty string."
        )


def _require_uuid_str_claim(claims: dict, name: str) -> None:
    v = claims.get(name)
    if not isinstance(v, str) or not v.strip():
        raise InvalidTokenError(
            f"Invalid token: claim '{name}' must be a non-empty string."
        )
    try:
        uuid.UUID(v)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidTokenError(
            f"Invalid token: claim '{name}' must be a UUID string."
        ) from exc


def _effective_issuer_audience(
    *,
    p: JwtVerifyParams,
    cfg_issuer: Optional[str],
    cfg_audience: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Apply per-profile defaults for issuer/audience enforcement.

    Rules:
    - If params explicitly provides issuer/audience, always use those values.
    - Otherwise, if the profile requires issuer/audience, default to configured values.
    - Otherwise (GENERIC), do not enforce issuer/audience by default.
    """
    issuer = p.issuer
    audience = p.audience

    profile = p.profile or JwtVerifyProfile.GENERIC

    if issuer is None and profile.require_issuer:
        issuer = cfg_issuer
    if audience is None and profile.require_audience:
        audience = cfg_audience

    return issuer, audience


class EdDsaJwtService(IJwtService):
    """
    EdDSA (Ed25519/Ed448) implementation of IJwtService with cached keystore loading.

    - Signs with the active key and includes kid in the header.
    - Verifies by requiring kid and alg=EdDSA (enforced by verify_eddsa_jwt).
    - Publishes JWKS from the cached keystore.
    """

    def __init__(self, config_provider=lambda: di.container.config):
        self._config = config_provider()
        self._keystore: Optional[EdDsaKeyStore] = load_eddsa_keystore_from_config(
            cfg=self._config,
        )
        self._keystore_view: Optional[IJwtKeyStore] = None

    @property
    def alg(self) -> str:
        return "EdDSA"

    @property
    def supports_jwks(self) -> bool:
        return True

    @property
    def keystore(self) -> Optional[IJwtKeyStore]:
        # Lazily create the public keystore view.
        if self._keystore_view is None:
            self._keystore_view = _EdDsaPublicKeyStore(
                keystore=self._get_keystore(),
                active_kid=str(self._config.acp.jwt.active_kid),
            )
        return self._keystore_view

    def _get_keystore(self) -> EdDsaKeyStore:
        return self._keystore

    def jwks(self) -> dict:
        return self._get_keystore().jwks()

    def sign(
        self,
        payload: Mapping[str, Any],
        *,
        params: Optional[JwtSignParams] = None,
    ) -> str:
        p = params or JwtSignParams()
        extra_headers = dict(p.headers) if p.headers else None
        return sign_eddsa_jwt(
            dict(payload),
            keystore=self._get_keystore(),
            kid=p.kid,
            extra_headers=extra_headers,
        )

    def verify(self, token: str, *, params: Optional[JwtVerifyParams] = None) -> dict:
        p = params or JwtVerifyParams()

        profile = p.profile or JwtVerifyProfile.GENERIC

        # Small clock-skew tolerance for multi-node deployments. Defaults to 60s unless
        # configured. Supported config keys: acp.jwt.leeway_seconds or acp.jwt.leeway.
        leeway_seconds = 60
        try:
            leeway_seconds = int(
                getattr(
                    self._config.acp.jwt,
                    "leeway_seconds",
                    getattr(self._config.acp.jwt, "leeway", 60),
                )
            )
        except Exception:  # pylint: disable=broad-exception-caught
            leeway_seconds = 60

        cfg_iss = self._config.acp.jwt.issuer
        cfg_aud = self._config.acp.jwt.audience

        issuer, audience = _effective_issuer_audience(
            p=p,
            cfg_issuer=cfg_iss,
            cfg_audience=cfg_aud,
        )

        claims = verify_eddsa_jwt(
            token,
            keystore=self._get_keystore(),
            verify_exp=p.verify_exp,
            leeway_seconds=leeway_seconds,
            issuer=issuer,
            audience=audience,
            required_claims=sorted(profile.required_claims),
        )

        required = profile.required_claims

        _require_claims_present(claims, required)

        # Stronger typing/shape checks for critical claims when required.
        if "sub" in required:
            _require_uuid_str_claim(claims, "sub")
        if "jti" in required:
            _require_uuid_str_claim(claims, "jti")
        if "type" in required:
            _require_nonempty_str_claim(claims, "type")
        if "token_version" in required and not isinstance(
            claims.get("token_version"), int
        ):
            raise InvalidTokenError(
                "Invalid token: claim 'token_version' must be an int."
            )

        # Enforce token kind when a profile is specific.
        if (
            profile.enforced_type is not None
            and claims.get("type") != profile.enforced_type
        ):
            raise InvalidTokenError("Invalid token type.")

        return claims
