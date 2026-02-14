"""Unit tests for mugen.core.plugin.acp.service.user."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
import re
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash


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
                debug=lambda *_: None,
                error=lambda *_: None,
                warning=lambda *_: None,
            ),
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.service import user as user_mod
from mugen.core.plugin.acp.service.user import UserService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class _Secret:
    def __init__(self, value: str):
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _UowContext:
    def __init__(self, uow):
        self._uow = uow

    async def __aenter__(self):
        return self._uow

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _service() -> UserService:
    svc = UserService.__new__(UserService)
    svc._logger = SimpleNamespace(
        debug=Mock(), error=Mock(), warning=Mock()
    )
    svc._config = SimpleNamespace(
        acp=SimpleNamespace(
            enforce_password_policy=True,
            password_policy=r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d).{8,}$",
            login_dummy_hash=generate_password_hash("dummy"),
        )
    )
    svc._resource = SimpleNamespace(
        namespace="com.test.acp"
    )
    svc._table = "acp_user"
    svc._grole_svc = SimpleNamespace(
        table="acp_global_role",
        get=AsyncMock(),
    )
    svc._grole_mship_svc = SimpleNamespace(
        table="acp_global_role_membership",
        clear_user_roles=AsyncMock(),
        associate_roles_with_user=AsyncMock(),
        get_role_memberships_by_user=AsyncMock(return_value=[]),
    )
    svc._person_svc = SimpleNamespace(
        table="acp_person",
        get=AsyncMock(),
        update_with_row_version=AsyncMock(),
    )
    svc._rtoken_svc = SimpleNamespace(
        table="acp_refresh_token"
    )
    svc._rsg = SimpleNamespace(
        delete_many=AsyncMock(),
        unit_of_work=lambda: _UowContext(SimpleNamespace()),
    )
    svc.get = AsyncMock()
    svc.update = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    svc.bump_token_version = AsyncMock()
    return svc


class _FakeInitRegistry:
    def __init__(self) -> None:
        self._resources = {
            "ACP.User": SimpleNamespace(service_key="user_svc", namespace="com.test"),
            "ACP.GlobalRole": SimpleNamespace(
                service_key="grole_svc", namespace="com.test"
            ),
            "ACP.GlobalRoleMembership": SimpleNamespace(
                service_key="mship_svc", namespace="com.test"
            ),
            "ACP.Person": SimpleNamespace(
                service_key="person_svc", namespace="com.test"
            ),
            "ACP.RefreshToken": SimpleNamespace(
                service_key="rtoken_svc", namespace="com.test"
            ),
        }
        self._services = {
            "grole_svc": object(),
            "mship_svc": object(),
            "person_svc": object(),
            "rtoken_svc": object(),
        }

    def get_resource_by_type(self, edm_type_name: str):
        return self._resources[edm_type_name]

    def get_edm_service(self, service_key: str):
        return self._services[service_key]


class TestMugenAcpServiceUser(unittest.IsolatedAsyncioTestCase):
    """Covers high-value branches in ACP UserService actions."""

    def test_provider_helpers_and_constructor(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            get_required_ext_service=Mock(return_value="registry"),
        )
        with patch.object(user_mod.di, "container", new=container):
            self.assertEqual(
                user_mod._config_provider(), "cfg"
            )
            self.assertEqual(
                user_mod._logger_provider(), "logger"
            )
            self.assertEqual(
                user_mod._registry_provider(), "registry"
            )

        cfg = SimpleNamespace(acp=SimpleNamespace(password_policy=r"^.{8,}$"))
        logger = Mock()
        registry = _FakeInitRegistry()
        svc = UserService(
            table="acp_user",
            rsg=Mock(),
            config_provider=lambda: cfg,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertEqual(svc.table, "acp_user")
        self.assertIs(svc._logger, logger)
        self.assertIs(
            svc._grole_svc, registry._services["grole_svc"]
        )

    def test_password_helpers_and_policy_validation(self) -> None:
        svc = _service()
        self.assertFalse(svc.validate_password_policy(None))
        self.assertTrue(svc.validate_password_policy("Abcdef12"))
        self.assertFalse(svc.validate_password_policy("weak"))
        self.assertIsNotNone(
            re.compile(svc._config.acp.password_policy)
        )

        pw_hash = svc.get_password_hash("Abcdef12")
        self.assertTrue(svc.verify_password_hash(pw_hash, "Abcdef12"))
        self.assertFalse(svc.verify_password_hash(pw_hash, "wrong"))

    async def test_bump_token_version_paths(self) -> None:
        svc = _service()
        user_id = uuid.uuid4()
        svc.get.return_value = SimpleNamespace(id=user_id, token_version=3)
        svc.update.return_value = SimpleNamespace(id=user_id, token_version=4)

        updated = await UserService.bump_token_version(svc, {"id": user_id})
        self.assertEqual(updated.token_version, 4)
        self.assertEqual(
            svc.update.await_args.kwargs["changes"],
            {"token_version": 4},
        )

        svc.get.return_value = None
        self.assertIsNone(await UserService.bump_token_version(svc, {"id": user_id}))

    async def test_entity_action_delete_and_lock_unlock_paths(self) -> None:
        svc = _service()
        user_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        data = SimpleNamespace(row_version=11)
        user = SimpleNamespace(id=user_id, deleted_at=None)
        updated = SimpleNamespace(id=user_id)

        svc.get.return_value = user
        svc.update_with_row_version.return_value = updated
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            _, status = await UserService.entity_action_delete(
                svc,
                entity_id=user_id,
                auth_user_id=actor_id,
                data=data,
            )
            self.assertEqual(status, 204)

            svc.update_with_row_version.side_effect = RowVersionConflict("rv")
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=user_id,
                    auth_user_id=actor_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version.side_effect = None
            svc.get.return_value = None
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=user_id,
                    auth_user_id=actor_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get.return_value = user
            svc.update_with_row_version.return_value = None
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=user_id,
                    auth_user_id=actor_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_entity_action_resetpasswordadmin_paths(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        user = SimpleNamespace(
            id=entity_id, password_hash=generate_password_hash("Oldpass12")
        )
        svc.get.return_value = user
        svc.update_with_row_version.return_value = user
        svc.bump_token_version = AsyncMock(return_value=user)
        data = SimpleNamespace(
            row_version=1,
            new_password=_Secret("Newpass12"),
            confirm_new_password=_Secret("Newpass12"),
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            _, status = await UserService.entity_action_resetpasswordadmin(
                svc,
                entity_id=entity_id,
                auth_user_id=actor_id,
                data=data,
            )
            self.assertEqual(status, 204)
            svc._rsg.delete_many.assert_awaited_once()

            mismatch = SimpleNamespace(
                row_version=1,
                new_password=_Secret("Newpass12"),
                confirm_new_password=_Secret("Mismatch12"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=actor_id,
                    data=mismatch,
                )
            self.assertEqual(ex.exception.code, 400)

            svc._config.acp.enforce_password_policy = (
                True
            )
            bad = SimpleNamespace(
                row_version=1,
                new_password=_Secret("weak"),
                confirm_new_password=_Secret("weak"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=actor_id,
                    data=bad,
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_entity_action_resetpassworduser_paths(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        other_id = uuid.uuid4()
        user = SimpleNamespace(
            id=entity_id, password_hash=generate_password_hash("Oldpass12")
        )
        svc.get.return_value = user
        svc.update_with_row_version.return_value = user
        svc.bump_token_version = AsyncMock(return_value=user)

        good_data = SimpleNamespace(
            row_version=3,
            current_password=_Secret("Oldpass12"),
            new_password=_Secret("Newpass12"),
            confirm_new_password=_Secret("Newpass12"),
        )
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=other_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 400)

            bad_current = SimpleNamespace(
                row_version=3,
                current_password=_Secret("bad"),
                new_password=_Secret("Newpass12"),
                confirm_new_password=_Secret("Newpass12"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=bad_current,
                )
            self.assertEqual(ex.exception.code, 401)

            _, status = await UserService.entity_action_resetpassworduser(
                svc,
                entity_id=entity_id,
                auth_user_id=entity_id,
                data=good_data,
            )
            self.assertEqual(status, 204)

    async def test_update_profile_and_roles_paths(self) -> None:
        svc = _service()
        user_id = uuid.uuid4()
        data = SimpleNamespace(
            row_version=5,
            model_dump=lambda exclude_none: {"row_version": 5, "first_name": "Alice"},
        )
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=uuid.uuid4(),
                    data=data,
                )
            self.assertEqual(ex.exception.code, 400)

        svc.get.return_value = SimpleNamespace(person_id=uuid.uuid4())
        svc._person_svc.update_with_row_version.return_value = (
            object()
        )
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            _, status = await UserService.entity_action_updateprofile(
                svc,
                entity_id=user_id,
                auth_user_id=user_id,
                data=data,
            )
            self.assertEqual(status, 204)

        auth_role_id = uuid.uuid4()
        admin_role_id = uuid.uuid4()
        svc.get.return_value = SimpleNamespace(id=user_id)
        svc._grole_svc.get = AsyncMock(
            side_effect=[
                SimpleNamespace(id=auth_role_id),
                SimpleNamespace(id=admin_role_id),
            ]
        )
        roles_data = SimpleNamespace(roles=["com.test:admin"])
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            _, status = await UserService.entity_action_updateroles(
                svc,
                entity_id=user_id,
                auth_user_id=user_id,
                data=roles_data,
            )
            self.assertEqual(status, 204)
        svc._grole_mship_svc.clear_user_roles.assert_awaited_once()
        svc._grole_mship_svc.associate_roles_with_user.assert_awaited_once()

    async def test_entity_set_action_provision_and_get_expanded(self) -> None:
        svc = _service()
        actor_id = uuid.uuid4()

        uow = SimpleNamespace(
            insert=AsyncMock(
                side_effect=[
                    {"id": uuid.uuid4()},
                    {"id": uuid.uuid4()},
                    {"id": uuid.uuid4()},
                ]
            ),
            get_one=AsyncMock(return_value={"id": uuid.uuid4()}),
        )
        svc._rsg.unit_of_work = lambda: _UowContext(
            uow
        )
        data = SimpleNamespace(
            first_name="Alice",
            last_name="Tester",
            username="alice",
            login_email="alice@example.com",
            password=_Secret("Abcdef12"),
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            _, status = await UserService.entity_set_action_provision(
                svc,
                auth_user_id=actor_id,
                data=data,
            )
            self.assertEqual(status, 204)

            svc._config.acp.enforce_password_policy = (
                True
            )
            bad_data = SimpleNamespace(
                first_name="Alice",
                last_name="Tester",
                username="alice",
                login_email="alice@example.com",
                password=_Secret("weak"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=actor_id,
                    data=bad_data,
                )
            self.assertEqual(ex.exception.code, 400)

        person_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role_id = uuid.uuid4()
        row = SimpleNamespace(id=user_id, person_id=person_id)
        svc.get = AsyncMock(return_value=row)
        svc._person_svc.get = AsyncMock(
            return_value=SimpleNamespace(id=person_id, first_name="Alice")
        )
        svc._grole_mship_svc.get_role_memberships_by_user = (
            AsyncMock(
                return_value=[SimpleNamespace(global_role_id=role_id)]
            )
        )
        svc._grole_svc.get = AsyncMock(
            return_value=SimpleNamespace(id=role_id, name="authenticated")
        )

        expanded = await UserService.get_expanded(svc, {"id": user_id})
        self.assertEqual(expanded.person.first_name, "Alice")
        self.assertEqual(expanded.global_roles[0].name, "authenticated")

    async def test_error_paths_raise_http_codes(self) -> None:
        svc = _service()
        user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=1)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)
