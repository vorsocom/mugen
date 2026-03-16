"""Unit tests for mugen.core.plugin.acp.api.func_auth."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.plugin.acp.api.decorator import auth as auth_decorator
from mugen.core.plugin.acp.api import func_auth


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            modules=SimpleNamespace(
                extensions=[
                    SimpleNamespace(
                        type="fw",
                        token="core.fw.acp",
                        namespace="com.test.admin",
                    )
                ]
            )
        ),
        acp=SimpleNamespace(
            login_dummy_hash="dummy-hash",
            login_access_expiry=30,
            login_refresh_expiry=60,
            jwt=SimpleNamespace(issuer="issuer", audience="aud"),
        ),
    )


def _registry(user_svc, refresh_svc):
    def _get(key: str):
        if key.endswith("ACP.User"):
            return user_svc
        if key.endswith("ACP.RefreshToken"):
            return refresh_svc
        raise AssertionError(f"Unexpected service key: {key}")

    return SimpleNamespace(get_edm_service=_get)


def _user(
    *,
    user_id: uuid.UUID | None = None,
    username: str = "alice",
    locked_at=None,
    token_version: int = 1,
    failed_login_count: int = 0,
    global_roles=None,
):
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        username=username,
        password_hash="hashed-password",
        locked_at=locked_at,
        token_version=token_version,
        failed_login_count=failed_login_count,
        global_roles=list(global_roles or []),
    )


def _refresh_token_row(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(token_hash="stored-hash", user_id=user_id)


def _services():
    user_svc = SimpleNamespace(
        get_expanded=AsyncMock(),
        update=AsyncMock(return_value=None),
        verify_password_hash=Mock(return_value=True),
    )
    refresh_svc = SimpleNamespace(
        create=AsyncMock(return_value=None),
        delete=AsyncMock(return_value=None),
        get=AsyncMock(return_value=None),
        verify_refresh_token_hash=AsyncMock(return_value=True),
        generate_refresh_token_hash=Mock(return_value="refresh-hash"),
    )
    jwt_svc = SimpleNamespace(
        jwks=Mock(return_value={"keys": []}),
        sign=Mock(side_effect=lambda payload: f"{payload['type']}-token"),
        verify=Mock(),
    )
    logger = Mock()
    return user_svc, refresh_svc, jwt_svc, logger


class TestMugenAcpFuncAuth(unittest.IsolatedAsyncioTestCase):
    """Covers login/logout/refresh endpoint logic and provider helpers."""

    async def test_provider_helpers_and_jwks(self) -> None:
        services = {
            func_auth.di.EXT_SERVICE_ADMIN_SVC_JWT: "jwt-svc",
            func_auth.di.EXT_SERVICE_ADMIN_REGISTRY: "registry-svc",
        }
        with patch.object(
            func_auth.di,
            "container",
            new=SimpleNamespace(
                config="cfg",
                logging_gateway="logger",
                get_required_ext_service=lambda key: services[key],
            ),
        ):
            self.assertEqual(func_auth._config_provider(), "cfg")
            self.assertEqual(func_auth._logger_provider(), "logger")
            self.assertEqual(func_auth._jwt_provider(), "jwt-svc")
            self.assertEqual(func_auth._registry_provider(), "registry-svc")

        jwt_svc = SimpleNamespace(jwks=Mock(return_value={"keys": [{"kid": "1"}]}))
        body, status = await func_auth.jwks(jwt_provider=lambda: jwt_svc)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"keys": [{"kid": "1"}]})

    async def test_user_login_validation_and_lookup_failures(self) -> None:
        user_svc, refresh_svc, jwt_svc, logger = _services()
        registry = _registry(user_svc, refresh_svc)

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"Username": "alice"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        user_svc.get_expanded = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(
                        return_value={"Username": "alice", "Password": "secret"}
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_user_login_not_found_locked_wrong_password(self) -> None:
        user_svc, refresh_svc, jwt_svc, logger = _services()
        registry = _registry(user_svc, refresh_svc)

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(
                        return_value={"Username": "alice", "Password": "secret"}
                    )
                ),
            ),
        ):
            user_svc.get_expanded = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 401)
            user_svc.verify_password_hash.assert_called_with("dummy-hash", "secret")

            locked_user = _user(locked_at=object())
            user_svc.get_expanded = AsyncMock(return_value=locked_user)
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 401)

            bad_password_user = _user(failed_login_count=2)
            user_svc.get_expanded = AsyncMock(return_value=bad_password_user)
            user_svc.verify_password_hash = Mock(return_value=False)
            user_svc.update = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 401)
            user_svc.update.assert_awaited_once_with(
                {"id": bad_password_user.id},
                {"failed_login_count": 3},
            )

            user_svc.update = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_user_login_success_and_persist_error(self) -> None:
        user_svc, refresh_svc, jwt_svc, logger = _services()
        registry = _registry(user_svc, refresh_svc)
        user = _user(global_roles=[SimpleNamespace(namespace="com.test", name="admin")])
        user_svc.get_expanded = AsyncMock(return_value=user)
        user_svc.verify_password_hash = Mock(return_value=True)

        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(
                    return_value={"Username": "alice", "Password": "secret"}
                )
            ),
        ):
            body, status = await func_auth.user_login(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["access_token"], "access-token")
        self.assertEqual(body["refresh_token"], "refresh-token")
        self.assertEqual(body["username"], "alice")
        self.assertEqual(body["user_id"], str(user.id))
        self.assertEqual(body["roles"], ["com.test:admin"])
        refresh_svc.create.assert_awaited_once()
        user_svc.update.assert_awaited_once()

        refresh_svc.create = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(
                        return_value={"Username": "alice", "Password": "secret"}
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await func_auth.user_login(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_user_logout_paths(self) -> None:
        endpoint = func_auth.user_logout.__wrapped__
        user_svc, refresh_svc, jwt_svc, logger = _services()
        registry = _registry(user_svc, refresh_svc)
        auth_user = str(uuid.uuid4())

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user=auth_user,
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value={})),
        ):
            body, status = await endpoint(
                auth_user=auth_user,
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        jwt_svc.verify = Mock(side_effect=InvalidTokenError())
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                auth_user=auth_user,
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        jwt_svc.verify = Mock(
            return_value={"sub": str(uuid.uuid4()), "jti": str(uuid.uuid4())}
        )
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user=auth_user,
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 401)

        jwt_svc.verify = Mock(return_value={"sub": auth_user, "jti": "bad-jti"})
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                auth_user=auth_user,
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        jwt_svc.verify = Mock(return_value={"sub": auth_user, "jti": str(uuid.uuid4())})
        refresh_svc.delete = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    auth_user=auth_user,
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

        refresh_svc.delete = AsyncMock(return_value=None)
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                auth_user=auth_user,
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

    async def test_user_refresh_paths_and_success(self) -> None:
        user_svc, refresh_svc, jwt_svc, logger = _services()
        registry = _registry(user_svc, refresh_svc)
        endpoint = func_auth.user_refresh_login

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value={})),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        jwt_svc.verify = Mock(side_effect=ExpiredSignatureError())
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 401)

        jwt_svc.verify = Mock(side_effect=InvalidTokenError("bad"))
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        for payload in [
            {"sub": str(uuid.uuid4())},
            {"sub": str(uuid.uuid4()), "jti": "bad-jti"},
        ]:
            jwt_svc.verify = Mock(return_value=payload)
            with patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ):
                body, status = await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
                self.assertEqual((body, status), ("", 204))

        jti = str(uuid.uuid4())
        jwt_svc.verify = Mock(
            return_value={"sub": str(uuid.uuid4()), "jti": jti, "token_version": 2}
        )
        refresh_svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

        refresh_svc.get = AsyncMock(return_value=None)
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        user_id = uuid.uuid4()
        refresh_svc.get = AsyncMock(return_value=_refresh_token_row(user_id))
        refresh_svc.verify_refresh_token_hash = AsyncMock(return_value=False)
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        refresh_svc.verify_refresh_token_hash = AsyncMock(return_value=True)
        user_svc.get_expanded = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

        user_svc.get_expanded = AsyncMock(return_value=None)
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        user_row = _user(user_id=user_id, token_version=3)
        user_svc.get_expanded = AsyncMock(return_value=user_row)
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
            self.assertEqual((body, status), ("", 204))

        jwt_svc.verify = Mock(
            return_value={"sub": str(user_id), "jti": jti, "token_version": 4}
        )
        locked_user = _user(user_id=user_id, token_version=4, locked_at=object())
        user_svc.get_expanded = AsyncMock(return_value=locked_user)
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 403)

        active_user = _user(
            user_id=user_id,
            token_version=4,
            global_roles=[SimpleNamespace(namespace="com.test", name="admin")],
        )
        user_svc.get_expanded = AsyncMock(return_value=active_user)
        jwt_svc.sign = Mock(side_effect=["new-access", "new-refresh"])
        refresh_svc.create = AsyncMock(side_effect=SQLAlchemyError("db"))
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"RefreshToken": "rt"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=_config,
                    logger_provider=lambda: logger,
                    jwt_provider=lambda: jwt_svc,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

        refresh_svc.create = AsyncMock(return_value=None)
        refresh_svc.delete = AsyncMock(return_value=None)
        jwt_svc.sign = Mock(side_effect=["ok-access", "ok-refresh"])
        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(return_value={"RefreshToken": "rt"})
            ),
        ):
            body, status = await endpoint(
                config_provider=_config,
                logger_provider=lambda: logger,
                jwt_provider=lambda: jwt_svc,
                registry_provider=lambda: registry,
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["access_token"], "ok-access")
        self.assertEqual(body["refresh_token"], "ok-refresh")
        self.assertEqual(body["user_id"], str(active_user.id))
        self.assertEqual(body["roles"], ["com.test:admin"])

    async def test_tenant_invitation_redeem_authenticated_paths(self) -> None:
        endpoint = func_auth.tenant_invitation_redeem_authenticated.__wrapped__
        logger = Mock()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        invitation_svc = SimpleNamespace(
            redeem_authenticated=AsyncMock(return_value=("", 204))
        )
        registry = SimpleNamespace(
            get_resource_by_type=Mock(return_value=SimpleNamespace(service_key="svc")),
            get_edm_service=Mock(return_value=invitation_svc),
        )

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(tenant_id),
                    invitation_id=str(invitation_id),
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value={})),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(tenant_id),
                    invitation_id=str(invitation_id),
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value={"Token": "x"})),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id="bad-tenant",
                    invitation_id=str(invitation_id),
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(tenant_id),
                    invitation_id="bad-invitation",
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(tenant_id),
                    invitation_id=str(invitation_id),
                    auth_user="bad-user",
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

        with patch.object(
            func_auth,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value={"Token": "abc"})),
        ):
            body, status = await endpoint(
                tenant_id=str(tenant_id),
                invitation_id=str(invitation_id),
                auth_user=str(auth_user),
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
            )
        self.assertEqual((body, status), ("", 204))
        invitation_svc.redeem_authenticated.assert_awaited_once_with(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            auth_user_id=auth_user,
            token="abc",
        )

        invitation_svc.redeem_authenticated = AsyncMock(
            side_effect=SQLAlchemyError("db")
        )
        with (
            patch.object(func_auth, "abort", side_effect=_abort_raiser),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value={"Token": "abc"})),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    tenant_id=str(tenant_id),
                    invitation_id=str(invitation_id),
                    auth_user=str(auth_user),
                    logger_provider=lambda: logger,
                    registry_provider=lambda: registry,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_tenant_invitation_redeem_authenticated_decorator(self) -> None:
        endpoint = func_auth.tenant_invitation_redeem_authenticated
        logger = Mock()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        invitation_svc = SimpleNamespace(
            redeem_authenticated=AsyncMock(return_value=("", 204))
        )
        registry = SimpleNamespace(
            get_resource_by_type=Mock(return_value=SimpleNamespace(service_key="svc")),
            get_edm_service=Mock(return_value=invitation_svc),
        )

        with (
            patch.object(
                auth_decorator,
                "_decode_access_token",
                return_value={"sub": str(auth_user)},
            ),
            patch.object(
                auth_decorator,
                "_require_user_from_token",
                new=AsyncMock(return_value=SimpleNamespace(id=auth_user)),
            ),
            patch.object(
                func_auth,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value={"Token": "abc"})),
            ),
        ):
            body, status = await endpoint(
                tenant_id=str(tenant_id),
                invitation_id=str(invitation_id),
                logger_provider=lambda: logger,
                registry_provider=lambda: registry,
            )

        self.assertEqual((body, status), ("", 204))
        invitation_svc.redeem_authenticated.assert_awaited_once_with(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            auth_user_id=auth_user,
            token="abc",
        )
