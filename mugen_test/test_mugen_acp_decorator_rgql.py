"""Unit tests for mugen.core.plugin.acp.api.decorator.rgql."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from quart import Quart
from sqlalchemy.exc import SQLAlchemyError


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(
            config=SimpleNamespace(),
            logging_gateway=SimpleNamespace(
                debug=lambda *_: None, error=lambda *_: None
            ),
            get_ext_service=lambda *_: None,
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.decorator import rgql as rgql_mod
from mugen.core.utility.rgql_helper.error import RGQLExpandError


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


@dataclass
class _Entity:
    id: uuid.UUID
    name: str
    role_id: uuid.UUID | None = None
    secret: str | None = None


class _FakeSemanticChecker:
    def __init__(self, model):
        self.model = model

    def check_url(self, _url) -> None:
        return None

    def materialize_expand_for_url(self, url):
        return list(url.query.expand or [])


class _FakeExpansionContext:
    def __init__(self, **kwargs):
        self.max_depth = kwargs["max_depth"]

    async def permitted(
        self, edm_type, path: str
    ) -> bool:
        return True


class _FakeEdmType:
    def __init__(self) -> None:
        self.name = "ACP.User"
        self.nav_properties = {
            "Role": SimpleNamespace(
                target_type=SimpleNamespace(name="ACP.GlobalRole", is_collection=False),
                source_fk="RoleId",
            )
        }

    def property_redacted(self, title: str) -> bool:
        return title == "Secret"


class _FakeSchema:
    def __init__(self) -> None:
        self._edm_type = _FakeEdmType()

    def get_type(self, _edm_type_name: str):
        return self._edm_type


class _FakeRegistry:
    def __init__(self, *, service, rgql_enabled: bool = True):
        self.schema_index = {"Users": "ACP.User"}
        self.schema = _FakeSchema()
        self._service = service
        self._resource = SimpleNamespace(
            service_key="user_svc",
            namespace="com.test.acp",
            behavior=SimpleNamespace(
                rgql_enabled=rgql_enabled,
                rgql_max_expand_depth=None,
            ),
        )
        self._resource_by_type = {
            "ACP.User": self._resource,
            "ACP.GlobalRole": SimpleNamespace(
                service_key="role_svc",
                namespace="com.test.acp",
            ),
        }

    def get_resource(self, _entity_set: str):
        return self._resource

    def get_resource_by_type(self, edm_type_name: str):
        return self._resource_by_type[edm_type_name]

    def get_edm_service(self, service_key: str):
        if service_key == "user_svc":
            return self._service
        return self._service


def _config():
    return SimpleNamespace(
        acp=SimpleNamespace(
            rgql_default_top=3,
            rgql_max_top=20,
            rgql_max_skip=50,
            rgql_max_select=3,
            rgql_max_orderby=2,
            rgql_max_expand_paths=3,
            rgql_allow_expand_wildcard=False,
            rgql_max_filter_terms=6,
            rgql_max_expand_depth=2,
        )
    )


def _rgql_url(*, opts):
    return SimpleNamespace(query=opts)


class TestMugenAcpDecoratorRgql(unittest.IsolatedAsyncioTestCase):
    """Covers guard rails and list/entity execution paths for RGQL decorator."""

    async def asyncSetUp(self) -> None:
        self.app = Quart("test-acp-rgql-decorator")

    def test_provider_helpers(self) -> None:
        services = {
            rgql_mod.di.EXT_SERVICE_ADMIN_SVC_AUTH: "auth-svc",
            rgql_mod.di.EXT_SERVICE_ADMIN_REGISTRY: "registry-svc",
        }
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            get_required_ext_service=lambda key: services[key],
        )
        with patch.object(rgql_mod.di, "container", new=container):
            self.assertEqual(
                rgql_mod._config_provider(), "cfg"
            )
            self.assertEqual(
                rgql_mod._logger_provider(), "logger"
            )
            self.assertEqual(
                rgql_mod._auth_provider(), "auth-svc"
            )
            self.assertEqual(
                rgql_mod._registry_provider(), "registry-svc"
            )

    async def test_unknown_entity_set_and_rgql_disabled(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())
        service = SimpleNamespace()
        registry = _FakeRegistry(service=service, rgql_enabled=True)
        registry.schema_index = {}

        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with patch.object(rgql_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 404)

        disabled_registry = _FakeRegistry(service=service, rgql_enabled=False)
        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: disabled_registry,
        )(_endpoint)
        with patch.object(rgql_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 403)

    async def test_tenant_and_auth_user_guards(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())
        registry = _FakeRegistry(service=SimpleNamespace(), rgql_enabled=True)
        wrapped = rgql_mod.rgql_enabled(
            tenant_kw="tenant_id",
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with patch.object(rgql_mod, "abort", side_effect=_abort_raiser):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(entity_set="Users", entity_id=None)
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        tenant_id="bad",
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        tenant_id=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 400)

            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        tenant_id=str(uuid.uuid4()),
                        auth_user="bad",
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_invalid_rgql_query_and_select_limit_guard(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        user_id = uuid.uuid4()
        service = SimpleNamespace(
            list=AsyncMock(return_value=[]),
            count=AsyncMock(return_value=0),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())

        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
            patch.object(
                rgql_mod, "parse_rgql_url", side_effect=rgql_mod.RGQLParseError("bad")
            ),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$filter=bad",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(user_id),
                    )
                self.assertEqual(ex.exception.code, 400)

        too_many_select = SimpleNamespace(
            select=["A", "B", "C", "D"],
            expand=[],
            count=False,
        )
        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
            patch.object(
                rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=too_many_select)
            ),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$select=A,B,C,D",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(user_id),
                    )
                self.assertEqual(ex.exception.code, 400)

    async def test_list_path_success_and_sql_error(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        rows = [
            _Entity(
                id=uuid.uuid4(),
                name="Alice",
                role_id=uuid.uuid4(),
                secret="hide-me",
            )
        ]
        service = SimpleNamespace(
            list=AsyncMock(return_value=rows),
            count=AsyncMock(return_value=1),
            get=AsyncMock(return_value=rows[0]),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())

        opts = SimpleNamespace(
            select=["Name"],
            expand=[SimpleNamespace(path="Role", levels=None)],
            count=True,
        )

        class _Adapter:
            def build_relational_query(self, _opts):
                return ([], [], None, None)

        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_filter_groups",
                side_effect=lambda filter_groups, where: filter_groups,
            ),
            patch.object(rgql_mod, "normalise_expand_levels", return_value=1),
            patch.object(
                rgql_mod, "expand_navs_bulk", new=AsyncMock(return_value=None)
            ),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$select=Name&$expand=Role&$count=true",
                method="GET",
            ):
                result = await wrapped(
                    entity_set="Users",
                    entity_id=None,
                    auth_user=str(uuid.uuid4()),
                )

        rgql = result["rgql"]
        self.assertEqual(rgql.count, 1)
        self.assertEqual(rgql.limit, 3)
        self.assertEqual(rgql.values[0]["Name"], "Alice")
        self.assertNotIn("Secret", rgql.values[0])

        service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_filter_groups",
                side_effect=lambda filter_groups, where: filter_groups,
            ),
            patch.object(rgql_mod, "normalise_expand_levels", return_value=1),
            patch.object(
                rgql_mod, "expand_navs_bulk", new=AsyncMock(return_value=None)
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$select=Name&$expand=Role",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 500)

    async def test_entity_path_and_expand_error(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        entity = _Entity(id=uuid.uuid4(), name="Alice")
        service = SimpleNamespace(
            get=AsyncMock(return_value=entity),
            list=AsyncMock(return_value=[entity]),
            count=AsyncMock(return_value=1),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())
        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with (
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {"deleted_at": None},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                side_effect=lambda where, delete_filter: {**where, **delete_filter},
            ),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                result = await wrapped(
                    entity_set="Users",
                    entity_id=str(entity.id),
                    auth_user=str(uuid.uuid4()),
                )
        self.assertEqual(result["rgql"].values[0]["Name"], "Alice")
        self.assertEqual(result["edm_type_name"], "ACP.User")

        missing_service = SimpleNamespace(
            get=AsyncMock(return_value=None),
            list=AsyncMock(return_value=[]),
            count=AsyncMock(return_value=0),
        )
        missing_wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: _FakeRegistry(service=missing_service),
        )(_endpoint)
        with (
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {"deleted_at": None},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                side_effect=lambda where, delete_filter: {**where, **delete_filter},
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await missing_wrapped(
                        entity_set="Users",
                        entity_id=str(entity.id),
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 404)

        expand_error = RGQLExpandError("expand failed")
        expand_error.status_code = 422
        expand_error.message = "expand failed"
        opts = SimpleNamespace(
            select=["Name"],
            expand=[SimpleNamespace(path="Role", levels=None)],
            count=False,
        )

        class _Adapter:
            def build_relational_query(self, _opts):
                return ([], [], None, None)

        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_filter_groups",
                side_effect=lambda filter_groups, where: filter_groups,
            ),
            patch.object(rgql_mod, "normalise_expand_levels", return_value=1),
            patch.object(
                rgql_mod, "expand_navs_bulk", new=AsyncMock(side_effect=expand_error)
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$select=Name&$expand=Role",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=None,
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 422)

    async def test_resource_path_permission_helper_and_expand_filtering(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        user_id = uuid.uuid4()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())
        service = SimpleNamespace(
            list=AsyncMock(return_value=[_Entity(id=uuid.uuid4(), name="Alice")]),
            count=AsyncMock(return_value=0),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)

        opts = SimpleNamespace(
            select=["Name"],
            expand=[
                SimpleNamespace(path="Missing", levels=None),
                SimpleNamespace(path="Role", levels=None),
            ],
            count=False,
        )

        class _Adapter:
            def build_relational_query(self, _opts):
                return ([], [], None, None)

        class _Ctx:
            def __init__(self, **kwargs):
                self.max_depth = kwargs["max_depth"]
                self._perm_provider = kwargs["path_permission_provider"]

            async def permitted(self, edm_type, path: str) -> bool:
                return await self._perm_provider(edm_type, path)

        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_Ctx),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_filter_groups",
                side_effect=lambda filter_groups, where: filter_groups,
            ),
            patch.object(rgql_mod, "normalise_expand_levels", return_value=1),
            patch.object(
                rgql_mod, "expand_navs_bulk", new=AsyncMock(return_value=None)
            ),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$expand=Missing,Role",
                method="GET",
            ):
                result = await wrapped(
                    entity_set="Users",
                    entity_id=None,
                    auth_user=str(user_id),
                )

        self.assertEqual(len(result["rgql"].expand), 1)
        self.assertEqual(result["rgql"].expand[0].path, "Role")
        auth_svc.has_permission.assert_awaited_once()
        self.assertEqual(
            auth_svc.has_permission.await_args.kwargs["permission_object"],
            "com.test.acp:global_role",
        )

    async def test_rgql_guard_branches_for_limits_and_expand_shapes(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        user_id = uuid.uuid4()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())
        service = SimpleNamespace(
            list=AsyncMock(return_value=[_Entity(id=uuid.uuid4(), name="Alice")]),
            count=AsyncMock(return_value=0),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)

        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        class _Adapter:
            def __init__(self, payload):
                self._payload = payload

            def build_relational_query(self, _opts):
                return self._payload

        with patch.object(rgql_mod, "abort", side_effect=_abort_raiser):
            for opts, payload in (
                (
                    SimpleNamespace(select=[], expand=[], count=False),
                    ([], [1, 2, 3], None, None),
                ),
                (
                    SimpleNamespace(select=[], expand=[], count=False),
                    ([], [], 999, None),
                ),
                (
                    SimpleNamespace(select=[], expand=[], count=False),
                    ([], [], 1, 999),
                ),
                (
                    SimpleNamespace(select=[], expand=[], count=False),
                    (
                        [
                            SimpleNamespace(
                                where=[1, 2, 3],
                                scalar_filters=[1, 2, 3],
                                text_filters=[1],
                            )
                        ],
                        [],
                        1,
                        0,
                    ),
                ),
            ):
                with (
                    patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
                    patch.object(
                        rgql_mod,
                        "RGQLToRelationalAdapter",
                        new=lambda payload=payload: _Adapter(payload),
                    ),
                    patch.object(
                        rgql_mod, "ExpansionContext", new=_FakeExpansionContext
                    ),
                    patch.object(
                        rgql_mod,
                        "parse_rgql_url",
                        return_value=_rgql_url(opts=opts),
                    ),
                    patch.object(
                        rgql_mod,
                        "make_default_where_provider",
                        return_value=lambda _edm_type_name: {},
                    ),
                    patch.object(
                        rgql_mod,
                        "apply_to_filter_groups",
                        side_effect=lambda filter_groups, where: filter_groups,
                    ),
                ):
                    async with self.app.test_request_context(
                        "/api/core/acp/v1/Users?$count=true",
                        method="GET",
                    ):
                        with self.assertRaises(_AbortCalled) as ex:
                            await wrapped(
                                entity_set="Users",
                                entity_id=None,
                                auth_user=str(user_id),
                            )
                        self.assertEqual(ex.exception.code, 400)

            wildcard_opts = SimpleNamespace(
                select=["Name"],
                expand=[SimpleNamespace(path="*", levels=None)],
                count=False,
            )
            with (
                patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
                patch.object(
                    rgql_mod,
                    "RGQLToRelationalAdapter",
                    new=lambda: _Adapter(([], [], None, None)),
                ),
                patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
                patch.object(
                    rgql_mod,
                    "parse_rgql_url",
                    return_value=_rgql_url(opts=wildcard_opts),
                ),
                patch.object(
                    rgql_mod,
                    "make_default_where_provider",
                    return_value=lambda _edm_type_name: {},
                ),
                patch.object(
                    rgql_mod,
                    "apply_to_filter_groups",
                    side_effect=lambda filter_groups, where: filter_groups,
                ),
            ):
                async with self.app.test_request_context(
                    "/api/core/acp/v1/Users?$expand=*",
                    method="GET",
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await wrapped(
                            entity_set="Users",
                            entity_id=None,
                            auth_user=str(user_id),
                        )
                    self.assertEqual(ex.exception.code, 400)

            multihop_opts = SimpleNamespace(
                select=["Name"],
                expand=[SimpleNamespace(path="Role/Parent", levels=None)],
                count=False,
            )
            with (
                patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
                patch.object(
                    rgql_mod,
                    "RGQLToRelationalAdapter",
                    new=lambda: _Adapter(([], [], None, None)),
                ),
                patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
                patch.object(
                    rgql_mod,
                    "parse_rgql_url",
                    return_value=_rgql_url(opts=multihop_opts),
                ),
                patch.object(
                    rgql_mod,
                    "make_default_where_provider",
                    return_value=lambda _edm_type_name: {},
                ),
                patch.object(
                    rgql_mod,
                    "apply_to_filter_groups",
                    side_effect=lambda filter_groups, where: filter_groups,
                ),
            ):
                async with self.app.test_request_context(
                    "/api/core/acp/v1/Users?$expand=Role/Parent",
                    method="GET",
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await wrapped(
                            entity_set="Users",
                            entity_id=None,
                            auth_user=str(user_id),
                        )
                    self.assertEqual(ex.exception.code, 400)

            expand_limit_opts = SimpleNamespace(
                select=["Name"],
                expand=[
                    SimpleNamespace(path="Role", levels=None),
                    SimpleNamespace(path="X", levels=None),
                    SimpleNamespace(path="Y", levels=None),
                    SimpleNamespace(path="Z", levels=None),
                ],
                count=False,
            )
            with (
                patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
                patch.object(
                    rgql_mod,
                    "RGQLToRelationalAdapter",
                    new=lambda: _Adapter(([], [], None, None)),
                ),
                patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
                patch.object(
                    rgql_mod,
                    "parse_rgql_url",
                    return_value=_rgql_url(opts=expand_limit_opts),
                ),
                patch.object(
                    rgql_mod,
                    "make_default_where_provider",
                    return_value=lambda _edm_type_name: {},
                ),
                patch.object(
                    rgql_mod,
                    "apply_to_filter_groups",
                    side_effect=lambda filter_groups, where: filter_groups,
                ),
            ):
                async with self.app.test_request_context(
                    "/api/core/acp/v1/Users?$expand=Role,X,Y,Z",
                    method="GET",
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await wrapped(
                            entity_set="Users",
                            entity_id=None,
                            auth_user=str(user_id),
                        )
                    self.assertEqual(ex.exception.code, 400)

            bad_levels_opts = SimpleNamespace(
                select=["Name"],
                expand=[SimpleNamespace(path="Role", levels="bad")],
                count=False,
            )
            with (
                patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
                patch.object(
                    rgql_mod,
                    "RGQLToRelationalAdapter",
                    new=lambda: _Adapter(([], [], None, None)),
                ),
                patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
                patch.object(
                    rgql_mod,
                    "parse_rgql_url",
                    return_value=_rgql_url(opts=bad_levels_opts),
                ),
                patch.object(
                    rgql_mod,
                    "make_default_where_provider",
                    return_value=lambda _edm_type_name: {},
                ),
                patch.object(
                    rgql_mod,
                    "apply_to_filter_groups",
                    side_effect=lambda filter_groups, where: filter_groups,
                ),
                patch.object(
                    rgql_mod,
                    "normalise_expand_levels",
                    side_effect=ValueError("bad levels"),
                ),
            ):
                async with self.app.test_request_context(
                    "/api/core/acp/v1/Users?$expand=Role($levels=bad)",
                    method="GET",
                ):
                    with self.assertRaises(_AbortCalled) as ex:
                        await wrapped(
                            entity_set="Users",
                            entity_id=None,
                            auth_user=str(user_id),
                        )
                    self.assertEqual(ex.exception.code, 400)

    async def test_entity_path_additional_error_branches(self) -> None:
        async def _endpoint(**kwargs):
            return kwargs

        entity = _Entity(id=uuid.uuid4(), name="Alice")
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        logger = SimpleNamespace(debug=Mock(), error=Mock())

        service = SimpleNamespace(
            get=AsyncMock(return_value=entity),
            list=AsyncMock(return_value=[entity]),
            count=AsyncMock(return_value=1),
        )
        registry = _FakeRegistry(service=service, rgql_enabled=True)
        wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: registry,
        )(_endpoint)

        with (
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id="bad-uuid",
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                return_value={str(i): i for i in range(7)},
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=str(entity.id),
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 400)

        sql_service = SimpleNamespace(
            get=AsyncMock(side_effect=SQLAlchemyError("boom")),
            list=AsyncMock(return_value=[]),
            count=AsyncMock(return_value=0),
        )
        sql_wrapped = rgql_mod.rgql_enabled(
            config_provider=_config,
            logger_provider=lambda: logger,
            auth_provider=lambda: auth_svc,
            registry_provider=lambda: _FakeRegistry(
                service=sql_service,
                rgql_enabled=True,
            ),
        )(_endpoint)
        with (
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                side_effect=lambda where, delete_filter: where,
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users", method="GET"
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await sql_wrapped(
                        entity_set="Users",
                        entity_id=str(entity.id),
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 500)

        opts = SimpleNamespace(
            select=["Name"],
            expand=[SimpleNamespace(path="Role", levels=None)],
            count=False,
        )

        class _Adapter:
            def build_relational_query(self, _opts):
                return ([], [], None, None)

        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                side_effect=lambda where, delete_filter: where,
            ),
            patch.object(
                rgql_mod,
                "normalise_expand_levels",
                side_effect=ValueError("bad levels"),
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$expand=Role",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=str(entity.id),
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 400)

        expand_error = RGQLExpandError("expand failed")
        expand_error.status_code = 422
        expand_error.message = "expand failed"
        with (
            patch.object(rgql_mod, "SemanticChecker", new=_FakeSemanticChecker),
            patch.object(rgql_mod, "RGQLToRelationalAdapter", new=lambda: _Adapter()),
            patch.object(rgql_mod, "ExpansionContext", new=_FakeExpansionContext),
            patch.object(rgql_mod, "parse_rgql_url", return_value=_rgql_url(opts=opts)),
            patch.object(
                rgql_mod,
                "make_default_where_provider",
                return_value=lambda _edm_type_name: {},
            ),
            patch.object(
                rgql_mod,
                "apply_to_where",
                side_effect=lambda where, delete_filter: where,
            ),
            patch.object(rgql_mod, "normalise_expand_levels", return_value=1),
            patch.object(
                rgql_mod, "expand_navs_bulk", new=AsyncMock(side_effect=expand_error)
            ),
            patch.object(rgql_mod, "abort", side_effect=_abort_raiser),
        ):
            async with self.app.test_request_context(
                "/api/core/acp/v1/Users?$expand=Role",
                method="GET",
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await wrapped(
                        entity_set="Users",
                        entity_id=str(entity.id),
                        auth_user=str(uuid.uuid4()),
                    )
                self.assertEqual(ex.exception.code, 422)
