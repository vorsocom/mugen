"""
Runtime-binding specifications for the admin control-plane.

These are *declarative* (pure) and safe to register in contrib and migrations.
They are materialized at runtime by a binder (e.g., AdminRuntimeBinder).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TableSpec:
    """
    Declares how to load a SQLAlchemy Table (or mapped class exposing __table__).
    """

    table_name: str
    table_provider: str  # "pkg.mod:Attr" (Attr may be Table or Model class)


@dataclass(frozen=True, slots=True)
class EdmTypeSpec:
    """
    Declares how to load an EdmType instance.
    """

    edm_type_name: str
    edm_provider: str  # "pkg.mod:edm_type_object"


@dataclass(frozen=True, slots=True)
class RelationalServiceSpec:
    """
    Declares how to instantiate a relational service at runtime.
    Binder injects rsg; init_kwargs are passed to the service ctor.
    """

    service_key: str
    service_cls: str  # "pkg.mod:ClassName"
    init_kwargs: Mapping[str, Any]
