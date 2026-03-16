"""Unit tests for ACP runtime binder edge and error branches."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mugen.core.plugin.acp.sdk.runtime_binder import (
    AdminRuntimeBinder,
    RuntimeBindingError,
    _load_attr,
)
from mugen.core.utility.rgql.model import EdmType


class _TableLike:  # pylint: disable=too-few-public-methods
    columns: tuple[str, ...] = ("id",)
    name = "fake_table"


class _ModelWithTable:  # pylint: disable=too-few-public-methods
    __table__ = _TableLike()


NOT_TABLE = object()
NOT_CALLABLE = 42

EDM_OK = EdmType(
    name="TEST.Widget",
    kind="entity",
    entity_set_name="Widgets",
)
EDM_NO_NAME = SimpleNamespace(entity_set_name="Widgets")
EDM_NO_ENTITY_SET = SimpleNamespace(name="TEST.Widget")


class _GoodService:  # pylint: disable=too-few-public-methods
    def __init__(self, *, rsg) -> None:
        self.rsg = rsg


class _ExplodingService:  # pylint: disable=too-few-public-methods
    def __init__(self, **kwargs) -> None:
        raise ValueError(f"boom: {kwargs}")


class _FakeRegistry:  # pylint: disable=too-few-public-methods
    def __init__(
        self,
        *,
        table_specs: list[object] | None = None,
        edm_specs: list[object] | None = None,
        service_specs: list[object] | None = None,
    ) -> None:
        self._table_specs = list(table_specs or [])
        self._edm_specs = list(edm_specs or [])
        self._service_specs = list(service_specs or [])
        self.tables = {}
        self.registered_schema = None
        self.registered_services = {}

    def table_specs(self) -> list[object]:
        return list(self._table_specs)

    def edm_type_specs(self) -> list[object]:
        return list(self._edm_specs)

    def service_specs(self) -> list[object]:
        return list(self._service_specs)

    def register_tables(self, tables: dict[str, object]) -> None:
        self.tables = dict(tables)

    def register_edm_schema(self, *, types: dict, entity_sets: dict) -> None:
        self.registered_schema = {
            "types": dict(types),
            "entity_sets": dict(entity_sets),
        }

    def register_edm_service(self, key: str, svc: object) -> None:
        self.registered_services[key] = svc


class TestRuntimeBinderEdgeCases(unittest.TestCase):
    """Covers RuntimeBindingError and binder validation branches."""

    def setUp(self) -> None:
        _load_attr.cache_clear()

    def test_runtime_binding_error_preserves_cause(self) -> None:
        cause = ValueError("inner")

        err = RuntimeBindingError(
            operation="bind_services",
            provider="mod:svc",
            detail="failed",
            cause=cause,
        )

        self.assertEqual(err.operation, "bind_services")
        self.assertIs(err.__cause__, cause)

    def test_load_attr_requires_provider_colon(self) -> None:
        with self.assertRaises(RuntimeBindingError):
            _load_attr("invalid_provider")

    def test_load_attr_raises_for_import_error(self) -> None:
        with self.assertRaises(RuntimeBindingError):
            _load_attr("does.not.exist.module:thing")

    def test_load_attr_raises_for_missing_attribute_path(self) -> None:
        with self.assertRaises(RuntimeBindingError):
            _load_attr("mugen.core.plugin.acp.sdk.runtime_binder:not_present")

    def test_bind_tables_rejects_invalid_provider(self) -> None:
        registry = _FakeRegistry(
            table_specs=[SimpleNamespace(table_name="widgets", table_provider=None)]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_tables()

    def test_bind_tables_rejects_invalid_table_name(self) -> None:
        provider = f"{__name__}:_ModelWithTable"
        registry = _FakeRegistry(
            table_specs=[SimpleNamespace(table_name="", table_provider=provider)]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_tables()

    def test_bind_tables_rejects_non_table_like_object(self) -> None:
        provider = f"{__name__}:NOT_TABLE"
        registry = _FakeRegistry(
            table_specs=[SimpleNamespace(table_name="widgets", table_provider=provider)]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_tables()

    def test_bind_edm_schema_rejects_invalid_provider_field(self) -> None:
        registry = _FakeRegistry(edm_specs=[SimpleNamespace(edm_provider=None)])

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_edm_schema()

    def test_bind_edm_schema_requires_name_and_entity_set_name(self) -> None:
        provider_no_name = f"{__name__}:EDM_NO_NAME"
        registry_no_name = _FakeRegistry(
            edm_specs=[SimpleNamespace(edm_provider=provider_no_name)]
        )

        binder = AdminRuntimeBinder(registry=registry_no_name, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_edm_schema()

        provider_no_set = f"{__name__}:EDM_NO_ENTITY_SET"
        registry_no_set = _FakeRegistry(
            edm_specs=[SimpleNamespace(edm_provider=provider_no_set)]
        )

        binder = AdminRuntimeBinder(registry=registry_no_set, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_edm_schema()

    def test_bind_services_supports_none_init_kwargs_and_injects_rsg(self) -> None:
        rsg = Mock()
        provider = f"{__name__}:_GoodService"
        registry = _FakeRegistry(
            service_specs=[
                SimpleNamespace(
                    service_key="svc.widgets",
                    service_cls=provider,
                    init_kwargs=None,
                )
            ]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=rsg)
        binder.bind_services()

        self.assertIn("svc.widgets", registry.registered_services)
        self.assertIs(registry.registered_services["svc.widgets"].rsg, rsg)

    def test_bind_services_rejects_invalid_provider_and_service_key(self) -> None:
        registry = _FakeRegistry(
            service_specs=[SimpleNamespace(service_key="svc", service_cls=None)]
        )
        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())
        with self.assertRaises(RuntimeBindingError):
            binder.bind_services()

        provider = f"{__name__}:_GoodService"
        registry = _FakeRegistry(
            service_specs=[
                SimpleNamespace(service_key="", service_cls=provider, init_kwargs={})
            ]
        )
        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())
        with self.assertRaises(RuntimeBindingError):
            binder.bind_services()

    def test_bind_services_rejects_non_mapping_init_kwargs(self) -> None:
        provider = f"{__name__}:_GoodService"
        registry = _FakeRegistry(
            service_specs=[
                SimpleNamespace(
                    service_key="svc.widgets",
                    service_cls=provider,
                    init_kwargs=5,
                )
            ]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_services()

    def test_bind_services_rejects_non_callable_loaded_object(self) -> None:
        provider = f"{__name__}:NOT_CALLABLE"
        registry = _FakeRegistry(
            service_specs=[
                SimpleNamespace(
                    service_key="svc.widgets",
                    service_cls=provider,
                    init_kwargs={},
                )
            ]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_services()

    def test_bind_services_wraps_instantiation_errors(self) -> None:
        provider = f"{__name__}:_ExplodingService"
        registry = _FakeRegistry(
            service_specs=[
                SimpleNamespace(
                    service_key="svc.widgets",
                    service_cls=provider,
                    init_kwargs={},
                )
            ]
        )

        binder = AdminRuntimeBinder(registry=registry, rsg=Mock())

        with self.assertRaises(RuntimeBindingError):
            binder.bind_services()
