"""Additional branch coverage tests for mugen.core.plugin.acp.service.user."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
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
    svc._logger = SimpleNamespace(debug=Mock(), error=Mock(), warning=Mock())
    svc._config = SimpleNamespace(
        acp=SimpleNamespace(
            enforce_password_policy=True,
            password_policy=r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d).{8,}$",
            login_dummy_hash=generate_password_hash("dummy"),
        )
    )
    svc._resource = SimpleNamespace(namespace="com.test.acp")
    svc._table = "acp_user"
    svc._grole_svc = SimpleNamespace(table="acp_global_role", get=AsyncMock())
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
    svc._rtoken_svc = SimpleNamespace(table="acp_refresh_token")
    svc._rsg = SimpleNamespace(
        delete_many=AsyncMock(),
        unit_of_work=lambda: _UowContext(SimpleNamespace()),
    )
    svc.get = AsyncMock()
    svc.update = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    svc.bump_token_version = AsyncMock()
    return svc


class TestMugenAcpServiceUserBranchEdges(unittest.IsolatedAsyncioTestCase):
    """Exercises remaining error and edge branches in UserService."""

    async def test_delete_error_branches(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=1)
        deleted_user = SimpleNamespace(id=entity_id, deleted_at=object())
        user = SimpleNamespace(id=entity_id, deleted_at=None)

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

        svc.get = AsyncMock(return_value=deleted_user)
        payload, status = await UserService.entity_action_delete(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(return_value=user)
            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.update_with_row_version = AsyncMock(return_value=user)
            svc.bump_token_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_delete(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_lock_and_unlock_edge_branches(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=2)
        user = SimpleNamespace(id=entity_id, deleted_at=None)

        svc.get = AsyncMock(return_value=user)
        svc.update_with_row_version = AsyncMock(return_value=user)
        svc.bump_token_version = AsyncMock(return_value=user)
        payload, status = await UserService.entity_action_lock(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        payload, status = await UserService.entity_action_unlock(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(return_value=user)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(return_value=user)
            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.update_with_row_version = AsyncMock(return_value=user)
            svc.bump_token_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_lock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(return_value=user)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.update_with_row_version = AsyncMock(return_value=user)
            svc.bump_token_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_unlock(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_resetpasswordadmin_error_branches(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        user = SimpleNamespace(
            id=entity_id,
            password_hash=generate_password_hash("Oldpass12"),
        )
        data = SimpleNamespace(
            row_version=3,
            new_password=_Secret("Newpass12"),
            confirm_new_password=_Secret("Newpass12"),
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(return_value=user)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.update_with_row_version = AsyncMock(return_value=user)
            svc.bump_token_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.bump_token_version = AsyncMock(return_value=user)
            svc._rsg.delete_many = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpasswordadmin(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_resetpassworduser_error_branches(self) -> None:
        svc = _service()
        entity_id = uuid.uuid4()
        user = SimpleNamespace(
            id=entity_id,
            password_hash=generate_password_hash("Oldpass12"),
        )
        good_data = SimpleNamespace(
            row_version=4,
            current_password=_Secret("Oldpass12"),
            new_password=_Secret("Newpass12"),
            confirm_new_password=_Secret("Newpass12"),
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(return_value=user)
            mismatch = SimpleNamespace(
                row_version=4,
                current_password=_Secret("Oldpass12"),
                new_password=_Secret("Newpass12"),
                confirm_new_password=_Secret("Mismatch12"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=mismatch,
                )
            self.assertEqual(ex.exception.code, 400)

            svc._config.acp.enforce_password_policy = True
            weak = SimpleNamespace(
                row_version=4,
                current_password=_Secret("Oldpass12"),
                new_password=_Secret("weak"),
                confirm_new_password=_Secret("weak"),
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=weak,
                )
            self.assertEqual(ex.exception.code, 400)

            svc._config.acp.enforce_password_policy = False
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.update_with_row_version = AsyncMock(return_value=user)
            svc.bump_token_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.bump_token_version = AsyncMock(return_value=user)
            svc._rsg.delete_many = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_resetpassworduser(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=entity_id,
                    data=good_data,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_updateprofile_and_updateroles_error_branches(self) -> None:
        svc = _service()
        user_id = uuid.uuid4()
        profile_data = SimpleNamespace(
            row_version=5,
            model_dump=lambda exclude_none: {"row_version": 5, "first_name": "A"},
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=profile_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=profile_data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(return_value=SimpleNamespace(person_id=uuid.uuid4()))
            svc._person_svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=profile_data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc._person_svc.update_with_row_version = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=profile_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc._person_svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateprofile(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=profile_data,
                )
            self.assertEqual(ex.exception.code, 404)

            role_data = SimpleNamespace(roles=["com.test:admin"])
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(return_value=SimpleNamespace(id=user_id))
            svc._grole_svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc._grole_svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc._grole_svc.get = AsyncMock(
                side_effect=[SimpleNamespace(id=uuid.uuid4()), None]
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc._grole_svc.get = AsyncMock(
                side_effect=[
                    SimpleNamespace(id=uuid.uuid4()),
                    SimpleNamespace(id=uuid.uuid4()),
                ]
            )
            svc._grole_mship_svc.clear_user_roles = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_action_updateroles(
                    svc,
                    entity_id=user_id,
                    auth_user_id=user_id,
                    data=role_data,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_provision_and_get_expanded_edges(self) -> None:
        svc = _service()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(
            first_name="Alice",
            last_name="Tester",
            username="alice",
            login_email="alice@example.com",
            password=_Secret("Abcdef12"),
        )

        with patch.object(user_mod, "abort", side_effect=_abort_raiser):
            failing_uow = SimpleNamespace(
                insert=AsyncMock(side_effect=SQLAlchemyError("boom"))
            )
            svc._rsg.unit_of_work = lambda: _UowContext(failing_uow)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            uow = SimpleNamespace(
                insert=AsyncMock(
                    side_effect=[
                        {"id": uuid.uuid4()},
                        SQLAlchemyError("boom"),
                    ]
                ),
                get_one=AsyncMock(return_value={"id": uuid.uuid4()}),
            )
            svc._rsg.unit_of_work = lambda: _UowContext(uow)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            uow = SimpleNamespace(
                insert=AsyncMock(
                    side_effect=[{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]
                ),
                get_one=AsyncMock(side_effect=SQLAlchemyError("boom")),
            )
            svc._rsg.unit_of_work = lambda: _UowContext(uow)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            uow = SimpleNamespace(
                insert=AsyncMock(
                    side_effect=[{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]
                ),
                get_one=AsyncMock(return_value=None),
            )
            svc._rsg.unit_of_work = lambda: _UowContext(uow)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            uow = SimpleNamespace(
                insert=AsyncMock(
                    side_effect=[
                        {"id": uuid.uuid4()},
                        {"id": uuid.uuid4()},
                        SQLAlchemyError("boom"),
                    ]
                ),
                get_one=AsyncMock(return_value={"id": uuid.uuid4()}),
            )
            svc._rsg.unit_of_work = lambda: _UowContext(uow)
            with self.assertRaises(_AbortCalled) as ex:
                await UserService.entity_set_action_provision(
                    svc,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(return_value=None)
        self.assertIsNone(await UserService.get_expanded(svc, {"id": uuid.uuid4()}))
