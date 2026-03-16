"""Key material provider implementations for ACP key references."""

__all__ = [
    "ManagedEncryptedKeyMaterialProvider",
    "ManagedKeyMaterialCipher",
    "LocalConfigKeyMaterialProvider",
    "KeyMaterialResolver",
]

import base64
import hashlib
import os
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken

from mugen.core import di
from mugen.core.plugin.acp.contract.service.key_provider import (
    IKeyMaterialProvider,
    ResolvedKeyMaterial,
)
from mugen.core.plugin.acp.domain import KeyRefDE
from mugen.core.utility.security import validate_acp_managed_secret_encryption_key


def _config_provider():
    return di.container.config


class LocalConfigKeyMaterialProvider(IKeyMaterialProvider):
    """Resolve key material from configured local maps and env indirection."""

    def __init__(self, config_provider=_config_provider):
        self._config_provider = config_provider

    @property
    def name(self) -> str:
        return "local"

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, SimpleNamespace):
            return vars(value)
        return {}

    @staticmethod
    def _resolve_secret(raw: Any) -> str | None:
        if raw is None:
            return None

        if isinstance(raw, Mapping):
            env_name = str(raw.get("env", "")).strip()
            if env_name:
                env_value = os.getenv(env_name, "").strip()
                return env_value or None

            value = str(raw.get("value", "")).strip()
            return value or None

        value = str(raw).strip()
        if value == "":
            return None

        if value.lower().startswith("env:"):
            env_name = value.split(":", 1)[1].strip()
            env_value = os.getenv(env_name, "").strip()
            return env_value or None

        return value

    def _lookup_local_secret(self, *, key_ref: KeyRefDE) -> str | None:
        config = self._config_provider()
        acp_cfg = getattr(config, "acp", SimpleNamespace())
        km_cfg = getattr(acp_cfg, "key_management", SimpleNamespace())
        providers_cfg = self._to_mapping(getattr(km_cfg, "providers", {}))
        local_cfg = self._to_mapping(providers_cfg.get("local", {}))

        key_map = self._to_mapping(local_cfg.get("keys", {}))

        by_purpose = key_map.get(str(key_ref.purpose or "").strip(), {})
        purpose_map = self._to_mapping(by_purpose)

        key_id = str(key_ref.key_id or "").strip()
        if key_id == "":
            return None

        raw = purpose_map.get(key_id)
        if raw is None:
            raw = key_map.get(key_id)

        return self._resolve_secret(raw)

    def _lookup_audit_hash_secret(self, key_id: str) -> str | None:
        config = self._config_provider()
        audit_cfg = getattr(config, "audit", SimpleNamespace())
        hash_cfg = getattr(audit_cfg, "hash_chain", SimpleNamespace())
        key_map = self._to_mapping(getattr(hash_cfg, "keys", {}))
        return self._resolve_secret(key_map.get(key_id))

    def resolve(self, key_ref: KeyRefDE) -> bytes | None:
        if str(key_ref.provider or "").strip().lower() != self.name:
            return None

        key_id = str(key_ref.key_id or "").strip()
        if key_id == "":
            return None

        secret = self._lookup_local_secret(key_ref=key_ref)
        if secret is None:
            secret = self._lookup_audit_hash_secret(key_id)

        if secret is None:
            return None

        return secret.encode("utf-8")


class ManagedKeyMaterialCipher:
    """Encrypt and decrypt ACP-managed secret material using one root key."""

    def __init__(self, config_provider=_config_provider) -> None:
        self._config_provider = config_provider

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, SimpleNamespace):
            return vars(value)
        return {}

    def _raw_encryption_key(self) -> str:
        config = self._config_provider()
        acp_cfg = getattr(config, "acp", SimpleNamespace())
        km_cfg = getattr(acp_cfg, "key_management", SimpleNamespace())
        providers_cfg = self._to_mapping(getattr(km_cfg, "providers", {}))
        managed_cfg = self._to_mapping(providers_cfg.get("managed", {}))
        raw_key = managed_cfg.get("encryption_key")
        return validate_acp_managed_secret_encryption_key(raw_key)

    def _cipher(self) -> Fernet:
        digest = hashlib.sha256(self._raw_encryption_key().encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, secret_value: str) -> str:
        """Encrypt one secret string for row-backed managed storage."""
        if not isinstance(secret_value, str):
            raise RuntimeError("SecretValue must be a string.")
        return self._cipher().encrypt(secret_value.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_secret: str) -> bytes:
        """Decrypt one row-backed managed secret value."""
        try:
            return self._cipher().decrypt(encrypted_secret.encode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError(
                "Stored managed key material could not be decrypted with "
                "acp.key_management.providers.managed.encryption_key."
            ) from exc


class ManagedEncryptedKeyMaterialProvider(IKeyMaterialProvider):
    """Resolve key material from row-backed managed ciphertext."""

    def __init__(
        self,
        config_provider=_config_provider,
        cipher: ManagedKeyMaterialCipher | None = None,
    ) -> None:
        self._cipher = cipher or ManagedKeyMaterialCipher(
            config_provider=config_provider
        )

    @property
    def name(self) -> str:
        return "managed"

    def resolve(self, key_ref: KeyRefDE) -> bytes | None:
        if str(key_ref.provider or "").strip().lower() != self.name:
            return None

        encrypted_secret = str(key_ref.encrypted_secret or "").strip()
        if encrypted_secret == "":
            return None

        return self._cipher.decrypt(encrypted_secret)


class KeyMaterialResolver:
    """Resolve key material through provider instances."""

    def __init__(
        self,
        providers: Sequence[IKeyMaterialProvider] | None = None,
    ) -> None:
        resolved = list(
            providers
            or [
                LocalConfigKeyMaterialProvider(),
                ManagedEncryptedKeyMaterialProvider(),
            ]
        )
        self._providers: dict[str, IKeyMaterialProvider] = {
            str(provider.name).strip().lower(): provider for provider in resolved
        }

    def resolve(self, key_ref: KeyRefDE) -> ResolvedKeyMaterial | None:
        provider_name = str(key_ref.provider or "").strip().lower()
        if provider_name == "":
            return None

        provider = self._providers.get(provider_name)
        if provider is None:
            return None

        secret = provider.resolve(key_ref)
        if secret is None:
            return None

        key_id = str(key_ref.key_id or "").strip()
        if key_id == "":
            return None

        return ResolvedKeyMaterial(
            key_id=key_id,
            secret=secret,
            provider=provider.name,
        )
