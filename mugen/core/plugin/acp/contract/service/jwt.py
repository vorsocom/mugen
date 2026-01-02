"""
Provides a service contract for JWT signing/verification operations.
"""

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Optional


class JwtVerifyProfile(str, enum.Enum):
    """
    Verification profiles define *semantic expectations* for a token, including:
    - which application claims must be present
    - whether token 'type' must match a specific value
    """

    GENERIC = "generic"
    PRINCIPAL = "principal"  # subject-bearing token, but no enforced 'type'
    ACCESS = "access"
    REFRESH = "refresh"

    @property
    def require_issuer(self) -> bool:
        """
        Whether issuer should be enforced by default when params.issuer is not provided.
        """
        return self in {
            JwtVerifyProfile.PRINCIPAL,
            JwtVerifyProfile.ACCESS,
            JwtVerifyProfile.REFRESH,
        }

    @property
    def require_audience(self) -> bool:
        """
        Whether audience should be enforced by default when params.audience is not provided.
        """
        return self in {
            JwtVerifyProfile.PRINCIPAL,
            JwtVerifyProfile.ACCESS,
            JwtVerifyProfile.REFRESH,
        }

    @property
    def enforced_type(self) -> Optional[str]:
        """
        If set, the 'type' claim must match this value.
        """
        if self == JwtVerifyProfile.ACCESS:
            return "access"
        if self == JwtVerifyProfile.REFRESH:
            return "refresh"
        return None

    @property
    def required_claims(self) -> set[str]:
        """
        Required claims for this profile (application policy).
        """
        base = {"exp", "iat", "nbf"}
        if self in (JwtVerifyProfile.ACCESS, JwtVerifyProfile.REFRESH):
            return base | {"sub", "jti", "type", "token_version"}
        if self == JwtVerifyProfile.PRINCIPAL:
            return base | {"sub"}
        return base


class IJwtKeyStore(ABC):
    """
    Public-key-focused keystore contract.

    This is intentionally shaped around verification and JWKS publication.
    It does not expose private key material.
    """

    @property
    @abstractmethod
    def active_kid(self) -> str:
        """The kid currently used for signing (if applicable)."""

    @abstractmethod
    def jwks(self) -> dict:
        """Return a JWKS document suitable for publishing."""

    @abstractmethod
    def has_kid(self, kid: str) -> bool:
        """Return True if the keystore contains a key matching kid."""


@dataclass(frozen=True)
class JwtVerifyParams:
    """
    Parameters controlling JWT verification.

    Notes
    -----
    - issuer/audience are optional to support environments that do not enforce them,
      but your current ACP usage does pass both.
    - profile is the preferred mechanism for expressing semantic expectations.
    - expected_type / require_subject are retained for backward compatibility and
      are mapped into a profile when profile is not provided.
    """

    verify_exp: bool = True
    issuer: Optional[str] = None
    audience: Optional[str] = None
    profile: Optional[JwtVerifyProfile] = JwtVerifyProfile.GENERIC


@dataclass(frozen=True)
class JwtSignParams:
    """
    Parameters controlling JWT signing.

    kid:
        Optionally force a specific key id. If None, the service uses its active key.
    headers:
        Additional headers to merge into the JWT header. Implementations should preserve
        algorithm safety invariants (e.g., must not allow overriding 'alg' to an
        unexpected value).
    """

    kid: Optional[str] = None
    headers: Optional[Mapping[str, Any]] = None


class IJwtService(ABC):
    """
    Contract for JWT signing/verification services across different algorithms.

    Implementations may back tokens with:
    - Local private keys (RS256/ES256/EdDSA) + JWKS publishing
    - Remote JWKS lookups (resource server scenario)
    - Symmetric secrets (HS256) (JWKS typically unsupported / empty)

    The interface is intentionally small: JWKS, sign, verify, and metadata.
    """

    @property
    @abstractmethod
    def alg(self) -> str:
        """
        The JWA algorithm string used by the service (e.g., "EdDSA", "ES256", "RS256",
        "HS256").
        """

    @property
    @abstractmethod
    def supports_jwks(self) -> bool:
        """
        Whether this service can publish a meaningful JWKS document.
        For asymmetric algorithms, this is typically True.
        """

    @property
    @abstractmethod
    def keystore(self) -> Optional[IJwtKeyStore]:
        """
        Keystore used by this service, if the service is keystore-backed.

        - Issuer services: typically present (local private key + public JWKS).
        - Resource servers using remote JWKS: may return None (no local keystore).
        - HS256-only services: usually None (JWKS is not meaningful).
        """

    @abstractmethod
    def jwks(self) -> dict:
        """
        Return a JWKS document (public keys).

        Returns
        -------
        dict
            Must be JSON-serializable. Recommended shape: {"keys": [...]}.

        Notes
        -----
        - For algorithms that cannot publish JWKS (e.g., HS256), implementations should
          either:
            (a) return {"keys": []}, or (b) raise NotImplementedError.
        """

    @abstractmethod
    def sign(
        self, payload: Mapping[str, Any], *, params: Optional[JwtSignParams] = None
    ) -> str:
        """
        Sign and return a compact JWS token.

        Parameters
        ----------
        payload:
            JWT claims.
        params:
            Optional signing directives (kid override, extra headers).
        """

    @abstractmethod
    def verify(self, token: str, *, params: Optional[JwtVerifyParams] = None) -> dict:
        """
        Verify a compact JWS token and return decoded claims.

        Parameters
        ----------
        token:
            Compact JWT.
        params:
            Optional verification directives (exp/iss/aud and token type enforcement).
        """
