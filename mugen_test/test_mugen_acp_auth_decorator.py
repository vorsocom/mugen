"""Unit tests for mugen.core.plugin.acp.api.decorator.auth."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.plugin.acp.api.decorator import auth as auth_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class _BadSub:
    def __str__(self):
        raise TypeError("bad-sub")


class _FakeCapabilities:
    def __init__(
        self, *, allowed_ops: set[str] | None = None, actions: dict | None = None
    ):
        self.allowed_ops = set(allowed_ops or [])
        self.actions = actions or {}
        self.last_op: str | None = None

    def op_allowed(self, op: str) -> bool:
        self.last_op = op
        return op in self.allowed_ops


class _FakeRegistry:
    def __init__(
        self, *, schema_index: dict | None = None, resource=None, user_svc=None
    ):
        self.schema_index = (
            schema_index if schema_index is not None else {"Users": object()}
        )
        self._resource = resource
        self._user_svc = user_svc

    def get_resource(self, _entity_set: str):
        return self._resource

    def get_edm_service(self, _key: str):
        return self._user_svc


class TestMugenAcpAuthDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers helper functions and permission decorator branches."""

    def _config(self):
        return SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="fw",
                            token="core.fw.acp",
                            namespace="Com.Test.Admin",
                        )
                    ]
                )
            )
        )

    async def test_provider_helpers_return_from_di_container(self) -> None:
        services = {
            auth_decorator.di.EXT_SERVICE_ADMIN_SVC_AUTH: "auth-svc",
            auth_decorator.di.EXT_SERVICE_ADMIN_REGISTRY: "registry",
            auth_decorator.di.EXT_SERVICE_ADMIN_SVC_JWT: "jwt",
        }

        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            get_required_ext_service=lambda key: services[key],
        )
        with patch.object(auth_decorator.di, "container", new=container):
            self.assertEqual(auth_decorator._config_provider(), "cfg")
            self.assertEqual(auth_decorator._logger_provider(), "logger")
            self.assertEqual(auth_decorator._auth_provider(), "auth-svc")
            self.assertEqual(auth_decorator._registry_provider(), "registry")
            self.assertEqual(auth_decorator._jwt_provider(), "jwt")

    async def test_get_bearer_token_from_header_paths(self) -> None:
        logger = Mock()
        with (
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
            patch.object(auth_decorator, "request", new=SimpleNamespace(headers={})),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._get_bearer_token_from_header(
                    logger_provider=lambda: logger
                )
            self.assertEqual(ex.exception.code, 401)
            logger.debug.assert_called_once_with("Authorization header missing.")

        logger = Mock()
        with (
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                auth_decorator,
                "request",
                new=SimpleNamespace(headers={"Authorization": "Token abc"}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._get_bearer_token_from_header(
                    logger_provider=lambda: logger
                )
            self.assertEqual(ex.exception.code, 401)
            logger.debug.assert_called_once_with("Invalid authorization header format.")

        with patch.object(
            auth_decorator,
            "request",
            new=SimpleNamespace(headers={"Authorization": "Bearer abc.def.ghi"}),
        ):
            self.assertEqual(
                auth_decorator._get_bearer_token_from_header(
                    logger_provider=lambda: Mock()
                ),
                "abc.def.ghi",
            )

    async def test_decode_access_token_paths(self) -> None:
        valid_sub = str(uuid.uuid4())
        jwt_svc = SimpleNamespace(
            verify=Mock(return_value={"sub": valid_sub, "token_version": 1})
        )
        with patch.object(
            auth_decorator, "_get_bearer_token_from_header", return_value="tok"
        ):
            token = auth_decorator._decode_access_token(
                logger_provider=lambda: Mock(),
                jwt_provider=lambda: jwt_svc,
            )
        self.assertEqual(token["sub"], valid_sub)

        with (
            patch.object(
                auth_decorator, "_get_bearer_token_from_header", return_value="tok"
            ),
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
        ):
            logger = Mock()
            jwt_svc = SimpleNamespace(verify=Mock(side_effect=ExpiredSignatureError()))
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._decode_access_token(
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                )
            self.assertEqual(ex.exception.code, 401)
            logger.debug.assert_called_once_with("Unauthorized request. Token expired.")

        with (
            patch.object(
                auth_decorator, "_get_bearer_token_from_header", return_value="tok"
            ),
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
        ):
            logger = Mock()
            jwt_svc = SimpleNamespace(verify=Mock(side_effect=InvalidTokenError()))
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._decode_access_token(
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                )
            self.assertEqual(ex.exception.code, 401)
            logger.debug.assert_called_once_with("Unauthorized request. Invalid token.")

        with (
            patch.object(
                auth_decorator, "_get_bearer_token_from_header", return_value="tok"
            ),
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
        ):
            logger = Mock()
            jwt_svc = SimpleNamespace(verify=Mock(return_value={"sub": _BadSub()}))
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._decode_access_token(
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                )
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with("Invalid token subject type.")

        with (
            patch.object(
                auth_decorator, "_get_bearer_token_from_header", return_value="tok"
            ),
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
        ):
            logger = Mock()
            jwt_svc = SimpleNamespace(verify=Mock(return_value={"sub": "not-a-uuid"}))
            with self.assertRaises(_AbortCalled) as ex:
                auth_decorator._decode_access_token(
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                )
            self.assertEqual(ex.exception.code, 401)
            logger.debug.assert_called_once_with("Invalid token subject.")

    async def test_require_user_from_token_paths(self) -> None:
        user_id = uuid.uuid4()
        token = {"sub": str(user_id), "token_version": 7}
        logger = Mock()

        async def _good_get(_where):
            return SimpleNamespace(
                id=user_id,
                deleted_at=None,
                locked_at=None,
                token_version=7,
                global_roles=[],
            )

        user_svc = SimpleNamespace(
            get=AsyncMock(side_effect=_good_get),
            get_expanded=AsyncMock(side_effect=_good_get),
        )
        registry = _FakeRegistry(
            resource=object(),
            user_svc=user_svc,
        )
        result = await auth_decorator._require_user_from_token(
            token,
            expanded=False,
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertEqual(result.id, user_id)
        user_svc.get.assert_awaited_once()

        await auth_decorator._require_user_from_token(
            token,
            expanded=True,
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        user_svc.get_expanded.assert_awaited_once()

        with (patch.object(auth_decorator, "abort", side_effect=_abort_raiser),):
            bad_svc = SimpleNamespace(
                get=AsyncMock(side_effect=SQLAlchemyError("boom")),
                get_expanded=AsyncMock(side_effect=SQLAlchemyError("boom")),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await auth_decorator._require_user_from_token(
                    token,
                    expanded=False,
                    config_provider=self._config,
                    logger_provider=lambda: logger,
                    registry_provider=lambda: _FakeRegistry(
                        resource=object(),
                        user_svc=bad_svc,
                    ),
                )
            self.assertEqual(ex.exception.code, 500)

            none_svc = SimpleNamespace(
                get=AsyncMock(return_value=None),
                get_expanded=AsyncMock(return_value=None),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await auth_decorator._require_user_from_token(
                    token,
                    expanded=False,
                    config_provider=self._config,
                    logger_provider=lambda: logger,
                    registry_provider=lambda: _FakeRegistry(
                        resource=object(),
                        user_svc=none_svc,
                    ),
                )
            self.assertEqual(ex.exception.code, 401)

            deleted = SimpleNamespace(
                id=user_id,
                deleted_at=object(),
                locked_at=None,
                token_version=7,
                global_roles=[],
            )
            with self.assertRaises(_AbortCalled) as ex:
                await auth_decorator._require_user_from_token(
                    token,
                    expanded=False,
                    config_provider=self._config,
                    logger_provider=lambda: logger,
                    registry_provider=lambda: _FakeRegistry(
                        resource=object(),
                        user_svc=SimpleNamespace(
                            get=AsyncMock(return_value=deleted),
                            get_expanded=AsyncMock(return_value=deleted),
                        ),
                    ),
                )
            self.assertEqual(ex.exception.code, 401)

            locked = SimpleNamespace(
                id=user_id,
                deleted_at=None,
                locked_at=object(),
                token_version=7,
                global_roles=[],
            )
            with self.assertRaises(_AbortCalled) as ex:
                await auth_decorator._require_user_from_token(
                    token,
                    expanded=False,
                    config_provider=self._config,
                    logger_provider=lambda: logger,
                    registry_provider=lambda: _FakeRegistry(
                        resource=object(),
                        user_svc=SimpleNamespace(
                            get=AsyncMock(return_value=locked),
                            get_expanded=AsyncMock(return_value=locked),
                        ),
                    ),
                )
            self.assertEqual(ex.exception.code, 401)

            stale = SimpleNamespace(
                id=user_id,
                deleted_at=None,
                locked_at=None,
                token_version=3,
                global_roles=[],
            )
            with self.assertRaises(_AbortCalled) as ex:
                await auth_decorator._require_user_from_token(
                    token,
                    expanded=False,
                    config_provider=self._config,
                    logger_provider=lambda: logger,
                    registry_provider=lambda: _FakeRegistry(
                        resource=object(),
                        user_svc=SimpleNamespace(
                            get=AsyncMock(return_value=stale),
                            get_expanded=AsyncMock(return_value=stale),
                        ),
                    ),
                )
            self.assertEqual(ex.exception.code, 401)

    async def test_global_auth_required_and_global_admin_required(self) -> None:
        user_id = uuid.uuid4()
        user = SimpleNamespace(id=user_id, global_roles=[])

        async def endpoint(**kwargs):
            return kwargs["auth_user"]

        wrapped = auth_decorator.global_auth_required(endpoint)
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=user),
            ) as require_user,
        ):
            result = await wrapped()
        self.assertEqual(result, str(user_id))
        self.assertEqual(require_user.await_args.kwargs["expanded"], False)

        admin_user = SimpleNamespace(
            id=user_id,
            global_roles=[
                SimpleNamespace(namespace="com.test.admin", name="administrator")
            ],
        )
        global_admin_wrapped = auth_decorator.global_admin_required(
            endpoint,
            config_provider=self._config,
            logger_provider=lambda: Mock(),
        )
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=admin_user),
            ) as require_user,
        ):
            admin_result = await global_admin_wrapped()
        self.assertEqual(admin_result, str(user_id))
        self.assertEqual(require_user.await_args.kwargs["expanded"], True)

        non_admin_user = SimpleNamespace(id=user_id, global_roles=[])
        with (
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=non_admin_user),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await global_admin_wrapped()
        self.assertEqual(ex.exception.code, 403)

        factory_auth_wrapped = auth_decorator.global_auth_required()(endpoint)
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=user),
            ),
        ):
            self.assertEqual(await factory_auth_wrapped(), str(user_id))

        factory_admin_wrapped = auth_decorator.global_admin_required(
            config_provider=self._config,
            logger_provider=lambda: Mock(),
        )(endpoint)
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=admin_user),
            ),
        ):
            self.assertEqual(await factory_admin_wrapped(), str(user_id))

    async def test_permission_required_branches_and_success_paths(self) -> None:
        user_id = uuid.uuid4()
        admin_role = SimpleNamespace(namespace="com.test.admin", name="administrator")

        resource = SimpleNamespace(
            capabilities=_FakeCapabilities(
                allowed_ops={"read"},
                actions={
                    "run": {"perm": "com.test.admin:execute", "is_admin_action": False},
                    "adminrun": {"perm": "", "is_admin_action": True},
                    "denied": {"perm": None},
                },
            ),
            permissions=SimpleNamespace(manage="com.test.admin:manage"),
            perm_obj="user",
        )
        registry = _FakeRegistry(resource=resource)
        logger = Mock()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))

        async def endpoint(**kwargs):
            return kwargs

        wrapped = auth_decorator.permission_required(
            permission_type="com.test.admin:read",
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
            auth_provider=lambda: auth_svc,
        )(endpoint)

        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=user_id,
                        global_roles=[],
                    )
                ),
            ),
        ):
            result = await wrapped(entity_set="Users")
        self.assertEqual(result["auth_user"], str(user_id))
        self.assertEqual(result["allow_global_admin"], False)
        auth_svc.has_permission.assert_awaited_once()

        wrapped_action = auth_decorator.permission_required(
            action_kw="action",
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
            auth_provider=lambda: auth_svc,
        )(endpoint)
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=user_id,
                        global_roles=[admin_role],
                    )
                ),
            ),
        ):
            action_result = await wrapped_action(entity_set="Users", action="run")
        self.assertEqual(action_result["auth_user"], str(user_id))

        wrapped_tenant = auth_decorator.permission_required(
            permission_type="com.test.admin:read",
            tenant_kw="tenant_id",
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
            auth_provider=lambda: auth_svc,
        )(endpoint)
        tenant_id = str(uuid.uuid4())
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=user_id,
                        global_roles=[],
                    )
                ),
            ),
        ):
            tenant_result = await wrapped_tenant(
                entity_set="Users", tenant_id=tenant_id
            )
        self.assertEqual(tenant_result["auth_user"], str(user_id))

        wrapped_admin_bypass = auth_decorator.permission_required(
            permission_type="com.test.admin:read",
            allow_global_admin=True,
            config_provider=self._config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
            auth_provider=lambda: auth_svc,
        )(endpoint)
        auth_svc.has_permission.reset_mock()
        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=user_id,
                        global_roles=[admin_role],
                    )
                ),
            ),
        ):
            bypass_result = await wrapped_admin_bypass(entity_set="Users")
        self.assertEqual(bypass_result["allow_global_admin"], True)
        auth_svc.has_permission.assert_not_awaited()

        with (
            patch.object(auth_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(user_id)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        id=user_id,
                        global_roles=[],
                    )
                ),
            ),
        ):
            no_entity = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await no_entity()
            self.assertEqual(ex.exception.code, 404)

            bad_registry = _FakeRegistry(schema_index={}, resource=resource)
            missing_entity = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: bad_registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await missing_entity(entity_set="Users")
            self.assertEqual(ex.exception.code, 404)

            invalid_perm = auth_decorator.permission_required(
                permission_type="read",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await invalid_perm(entity_set="Users")
            self.assertEqual(ex.exception.code, 500)

            op_forbidden_resource = SimpleNamespace(
                capabilities=_FakeCapabilities(allowed_ops=set(), actions={}),
                permissions=SimpleNamespace(manage="com.test.admin:manage"),
                perm_obj="user",
            )
            op_forbidden_registry = _FakeRegistry(resource=op_forbidden_resource)
            op_forbidden = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: op_forbidden_registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await op_forbidden(entity_set="Users")
            self.assertEqual(ex.exception.code, 405)

            missing_action_param = auth_decorator.permission_required(
                action_kw="action",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await missing_action_param(entity_set="Users")
            self.assertEqual(ex.exception.code, 400)

            unknown_action = auth_decorator.permission_required(
                action_kw="action",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await unknown_action(entity_set="Users", action="missing")
            self.assertEqual(ex.exception.code, 405)

            denied_action = auth_decorator.permission_required(
                action_kw="action",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await denied_action(entity_set="Users", action="denied")
            self.assertEqual(ex.exception.code, 405)

            admin_action = auth_decorator.permission_required(
                action_kw="action",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await admin_action(entity_set="Users", action="adminrun")
            self.assertEqual(ex.exception.code, 403)

            tenant_missing = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                tenant_kw="tenant_id",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await tenant_missing(entity_set="Users")
            self.assertEqual(ex.exception.code, 400)

            tenant_bad = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                tenant_kw="tenant_id",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await tenant_bad(entity_set="Users", tenant_id="not-a-uuid")
            self.assertEqual(ex.exception.code, 400)

            auth_svc.has_permission = AsyncMock(return_value=False)
            denied = auth_decorator.permission_required(
                permission_type="com.test.admin:read",
                config_provider=self._config,
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
                auth_provider=lambda: auth_svc,
            )(endpoint)
            with self.assertRaises(_AbortCalled) as ex:
                await denied(entity_set="Users")
            self.assertEqual(ex.exception.code, 403)
