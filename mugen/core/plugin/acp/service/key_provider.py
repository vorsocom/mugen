"""Key material provider implementations for ACP key references."""

__all__ = [
    "LocalConfigKeyMaterialProvider",
    "KeyMaterialResolver",
]

import os
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from mugen.core import di
from mugen.core.plugin.acp.contract.service.key_provider import (
    IKeyMaterialProvider,
    ResolvedKeyMaterial,
)
from mugen.core.plugin.acp.domain import KeyRefDE


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


class KeyMaterialResolver:
    """Resolve key material through provider instances."""

    def __init__(
        self,
        providers: Sequence[IKeyMaterialProvider] | None = None,
    ) -> None:
        resolved = list(providers or [LocalConfigKeyMaterialProvider()])
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
