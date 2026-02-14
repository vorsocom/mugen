"""
mugen.core.plugin.acp.sdk.runtime_binder
========================================

This module materializes *declarative* runtime-binding specifications registered on an
:class:`~mugen.core.plugin.acp.contract.sdk.registry.IAdminRegistry` into concrete
runtime registrations.

Background and intent
---------------------
The admin plugin uses a two-phase model:

1) **Contribution phase** (pure / migration-safe)
   - Plugins call ``contribute(...)`` and register *declarations* (
     resources, permissions, roles, grants, flags) and (optionally)
     *binding specs* as inert metadata (typically string import paths plus
     small primitives).
   - This phase is safe to run under Alembic migrations because it must not import or
     instantiate runtime-only dependencies (
     web framework objects, DI container, SQLAlchemy engines/sessions, etc.).

2) **Binding phase** (runtime-only)
   - This module executes during application startup (
     e.g., inside ``AdminFWExtension.setup()``) and turns the
     declarative specs into runtime registrations:
       * SQLAlchemy tables registered into the admin registry and the
         relational storage gateway
       * RGQL EDM schema (types and entity sets) registered into the admin registry
       * Relational service instances created and registered under their service keys

This separation ensures:
- `contrib` remains pure and deterministic for migrations.
- Runtime wiring is centralized and uniform across many downstream plugins.
- The admin registry can be frozen deterministically after binding is complete.

Usage
-----
Typical startup sequence:

    registry = AdminRegistry(...)
    contribute_all(registry, mugen_cfg)
    AdminRuntimeBinder(registry, rsg).bind_all()
    registry.freeze()

Notes
-----
- This module intentionally performs dynamic imports (``importlib``). Spec strings are
  expected to be stable, fully-qualified import references of the form
  ``"pkg.mod:attr"``.
- Errors are wrapped with context (spec/provider string) to make misconfiguration easier
  to diagnose.
"""

from __future__ import annotations

import importlib
import logging
from functools import lru_cache
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.utility.rgql.model import EdmType, EntitySet, TypeRef

logger = logging.getLogger(__name__)


class RuntimeBindingError(RuntimeError):
    """
    Raised when a runtime binding spec cannot be materialized.

    Attributes
    ----------
    operation:
        The binding operation being performed (e.g., "load_attr", "bind_tables").
    provider:
        The import provider string that failed (e.g., "pkg.mod:Symbol").
    detail:
        A human-readable description of what failed and why.
    """

    def __init__(
        self,
        *,
        operation: str,
        provider: str,
        detail: str,
        cause: Exception | None = None,
    ):
        self.operation = operation
        self.provider = provider
        self.detail = detail
        msg = f"{operation} failed for provider '{provider}': {detail}"
        super().__init__(msg)
        if cause is not None:
            self.__cause__ = cause


@lru_cache(maxsize=512)
def _load_attr(provider: str) -> Any:
    """
    Load a Python attribute from a fully-qualified provider string.

    Parameters
    ----------
    provider:
        Import reference in the form ``"package.module:attr.subattr"``.

    Returns
    -------
    Any
        The resolved Python object.

    Raises
    ------
    RuntimeBindingError
        If the module cannot be imported or the attribute path cannot be resolved.

    Examples
    --------
    - ``"mugen.core.plugin.acp.model.user:User"`` -> a mapped class
    - ``"mugen.core.plugin.acp.edm:user_type"`` -> an EdmType instance
    - ``"mugen.core.plugin.acp.service.user:UserService"`` -> a service class
    """
    if ":" not in provider:
        raise RuntimeBindingError(
            operation="load_attr",
            provider=provider,
            detail="Provider must be in the form 'package.module:attr[.subattr]'.",
        )

    mod_path, attr_path = provider.split(":", 1)
    try:
        obj: Any = importlib.import_module(mod_path)
    except Exception as e:
        raise RuntimeBindingError(
            operation="load_attr",
            provider=provider,
            detail=f"Could not import module '{mod_path}'.",
            cause=e,
        ) from e

    try:
        for part in attr_path.split("."):
            obj = getattr(obj, part)
    except Exception as e:
        raise RuntimeBindingError(
            operation="load_attr",
            provider=provider,
            detail=(
                f"Could not resolve attribute path '{attr_path}' in module"
                f" '{mod_path}'."
            ),
            cause=e,
        ) from e

    return obj


class AdminRuntimeBinder:
    """
    Materializes declarative registry binding specs into runtime registrations.

    This class is intentionally narrow: it reads spec objects already stored on
    the registry (via ``registry.table_specs()``,
    ``registry.edm_type_specs()``, ``registry.service_specs()``) and performs
    the runtime actions required to make the admin control-plane operational.

    Parameters
    ----------
    registry:
        The admin registry instance that contains declarative binding specs and receives
        runtime registrations.
    rsg:
        Relational storage gateway used to register SQLAlchemy tables and injected into
        relational services.

    Operational guidance
    --------------------
    - Run the binder *before* freezing the registry.
    - ``bind_all()`` executes in a safe dependency order
      (tables -> EDM schema -> services).
    - If any binding spec is invalid, a :class:`RuntimeBindingError` is raised
      with context.
    """

    def __init__(
        self, registry: IAdminRegistry, rsg: IRelationalStorageGateway
    ) -> None:
        self._registry = registry
        self._rsg = rsg

    def bind_tables(self) -> None:
        """
        Load and register all SQLAlchemy tables declared in the registry.

        Expected spec contract
        ----------------------
        Each item returned by ``registry.table_specs()`` must expose:
        - ``table_name``: str
        - ``table_provider``: str  (provider string "pkg.mod:Symbol")

        Provider resolution
        -------------------
        The loaded object may be either:
        - a SQLAlchemy ``Table`` instance, or
        - a mapped model class exposing ``__table__``.

        Side effects
        ------------
        - Calls ``registry.register_tables({...})``.
        - Calls ``rsg.register_tables(registry.tables)`` to keep the storage
          gateway in sync.

        Raises
        ------
        RuntimeBindingError
            If a provider cannot be loaded or does not yield a table-like object.
        """
        tables: dict[str, Any] = {}

        for spec in self._registry.table_specs():
            provider = getattr(spec, "table_provider", None)
            table_name = getattr(spec, "table_name", None)

            if not isinstance(provider, str) or not provider:
                raise RuntimeBindingError(
                    operation="bind_tables",
                    provider=str(provider),
                    detail=(
                        "Spec must define non-empty string attribute 'table_provider'."
                    ),
                )
            if not isinstance(table_name, str) or not table_name:
                raise RuntimeBindingError(
                    operation="bind_tables",
                    provider=provider,
                    detail="Spec must define non-empty string attribute 'table_name'.",
                )

            obj = _load_attr(provider)
            table = getattr(obj, "__table__", obj)

            # Minimal sanity check without importing SQLAlchemy Table type explicitly.
            # SQLAlchemy Table objects typically have .columns and .name.
            if not hasattr(table, "columns") or not hasattr(table, "name"):
                raise RuntimeBindingError(
                    operation="bind_tables",
                    provider=provider,
                    detail=(
                        "Loaded object is neither a Table nor a mapped class exposing"
                        " '__table__'."
                    ),
                )

            tables[table_name] = table

        self._registry.register_tables(tables)
        self._rsg.register_tables(self._registry.tables)

        logger.debug(
            "Bound %d tables into registry and relational gateway.", len(tables)
        )

    def bind_edm_schema(self) -> None:
        """
        Load and register the RGQL EDM schema declared in the registry.

        Expected spec contract
        ----------------------
        Each item returned by ``registry.edm_type_specs()`` must expose:
        - ``edm_provider``: str  (provider string "pkg.mod:Symbol")
        - (optional) ``edm_type_name``: str (informational; the loaded object
          is authoritative)

        Provider resolution
        -------------------
        The loaded object is expected to be an
        :class:`~mugen.core.utility.rgql.model.EdmType` (or a compatible
        object) with:
        - ``name``: str
        - ``entity_set_name``: str

        Behavior
        --------
        - Builds:
          * ``types`` mapping of EDM type name -> EdmType
          * ``entity_sets`` mapping of entity set name -> EntitySet(TypeRef(type.name))
        - Registers the schema via ``registry.register_edm_schema(...)``.

        Raises
        ------
        RuntimeBindingError
            If a provider cannot be loaded or does not yield an
            EdmType-compatible object.
        """
        schema_types: dict[str, EdmType] = {}
        schema_sets: dict[str, EntitySet] = {}

        for spec in self._registry.edm_type_specs():
            provider = getattr(spec, "edm_provider", None)
            if not isinstance(provider, str) or not provider:
                raise RuntimeBindingError(
                    operation="bind_edm_schema",
                    provider=str(provider),
                    detail=(
                        "Spec must define non-empty string attribute 'edm_provider'."
                    ),
                )

            edm_type = _load_attr(provider)

            name = getattr(edm_type, "name", None)
            entity_set_name = getattr(edm_type, "entity_set_name", None)

            if not isinstance(name, str) or not name:
                raise RuntimeBindingError(
                    operation="bind_edm_schema",
                    provider=provider,
                    detail=(
                        "Loaded EDM object missing non-empty string attribute 'name'."
                    ),
                )
            if not isinstance(entity_set_name, str) or not entity_set_name:
                raise RuntimeBindingError(
                    operation="bind_edm_schema",
                    provider=provider,
                    detail=(
                        "Loaded EDM object missing non-empty string attribute"
                        " 'entity_set_name'."
                    ),
                )

            schema_types[name] = edm_type
            schema_sets[entity_set_name] = EntitySet(
                name=entity_set_name,
                type=TypeRef(name),
                is_singleton=False,
            )

        self._registry.register_edm_schema(types=schema_types, entity_sets=schema_sets)

        logger.debug(
            "Bound EDM schema: %d types, %d entity sets.",
            len(schema_types),
            len(schema_sets),
        )

    def bind_services(self) -> None:
        """
        Instantiate and register all relational services declared in the registry.

        Expected spec contract
        ----------------------
        Each item returned by ``registry.service_specs()`` must expose:
        - ``service_key``: str
        - ``service_cls``: str  (provider string "pkg.mod:ClassName")
        - ``init_kwargs``: Mapping[str, Any]

        Injection policy
        ---------------
        The binder injects ``rsg=self._rsg`` into each service constructor.
        Any additional constructor args must be supplied in ``init_kwargs``.

        Raises
        ------
        RuntimeBindingError
            If a provider cannot be loaded, is not callable, or instantiation fails.
        """
        for spec in self._registry.service_specs():
            provider = getattr(spec, "service_cls", None)
            service_key = getattr(spec, "service_key", None)
            init_kwargs = getattr(spec, "init_kwargs", None)

            if not isinstance(provider, str) or not provider:
                raise RuntimeBindingError(
                    operation="bind_services",
                    provider=str(provider),
                    detail="Spec must define non-empty string attribute 'service_cls'.",
                )
            if not isinstance(service_key, str) or not service_key:
                raise RuntimeBindingError(
                    operation="bind_services",
                    provider=provider,
                    detail="Spec must define non-empty string attribute 'service_key'.",
                )
            if init_kwargs is None:
                init_kwargs = {}
            if not isinstance(init_kwargs, Mapping):
                raise RuntimeBindingError(
                    operation="bind_services",
                    provider=provider,
                    detail=(
                        "Spec attribute 'init_kwargs' must be a mapping (dict-like)."
                    ),
                )

            svc_cls = _load_attr(provider)
            if not callable(svc_cls):
                raise RuntimeBindingError(
                    operation="bind_services",
                    provider=provider,
                    detail=(
                        "Loaded service object is not callable (expected a class or"
                        " factory)."
                    ),
                )

            kwargs = dict(init_kwargs)
            kwargs["rsg"] = self._rsg

            try:
                svc = svc_cls(**kwargs)
            except Exception as e:
                raise RuntimeBindingError(
                    operation="bind_services",
                    provider=provider,
                    detail=f"Service instantiation failed for key '{service_key}'.",
                    cause=e,
                ) from e

            self._registry.register_edm_service(service_key, svc)

        logger.debug(
            "Bound %d services into registry.", len(self._registry.service_specs())
        )

    def bind_all(self) -> None:
        """
        Convenience method to bind all runtime artifacts in dependency order.

        Order
        -----
        1) tables
        2) EDM schema
        3) services

        This ordering is a safe default:
        - services commonly depend on tables being registered in the gateway
        - EDM schema is typically required before RGQL parsing/validation and expansion
        """
        self.bind_tables()
        self.bind_edm_schema()
        self.bind_services()
