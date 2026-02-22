"""Tests ACP TenantInvitationService token, delivery, and redeem lifecycle logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
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
            logging_gateway=SimpleNamespace(),
            email_gateway=None,
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.email import EmailGatewayError
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.service import tenant_invitation as invitation_mod
from mugen.core.plugin.acp.service.tenant_invitation import TenantInvitationService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _invitation(
    *,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    email: str = "user@example.com",
    status: str = "invited",
    row_version: int = 1,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=invitation_id,
        tenant_id=tenant_id,
        email=email,
        invited_by_user_id=None,
        token_hash="hash",
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(days=1)),
        accepted_at=None,
        accepted_by_user_id=None,
        revoked_at=None,
        revoked_by_user_id=None,
        status=status,
        row_version=row_version,
    )


def _service() -> TenantInvitationService:
    svc = TenantInvitationService.__new__(TenantInvitationService)
    svc._config = SimpleNamespace(
        acp=SimpleNamespace(
            argon2=SimpleNamespace(
                time_cost=1,
                memory_cost=1024,
                parallelism=1,
                hash_len=16,
            ),
            refresh_token_pepper="pepper",
            tenant_invitation_ttl_seconds=3600,
            tenant_invitation_invite_base_url="https://invite.example.com/redeem",
        )
    )
    svc._logger = SimpleNamespace(debug=Mock(), warning=Mock())
    svc._registry_provider = lambda: None
    svc._tenant_membership_svc = SimpleNamespace(
        get=AsyncMock(),
        create=AsyncMock(),
        update_with_row_version=AsyncMock(),
    )
    svc._user_svc = SimpleNamespace(get=AsyncMock())
    svc._ph = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1, hash_len=16)
    svc._rsg = SimpleNamespace(insert_one=AsyncMock())
    svc._de_type = invitation_mod.TenantInvitationDE
    svc._table = "admin_tenant_invitation"
    svc.get = AsyncMock()
    svc.update = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    return svc


class _GatewayOk:
    def __init__(self, events: list[str]):
        self._events = events
        self.requests: list = []

    async def send_email(self, request):
        self._events.append("send")
        self.requests.append(request)
        return SimpleNamespace(message_id="id")


class _GatewayFail:
    async def send_email(self, request):  # noqa: ARG002
        raise EmailGatewayError(
            provider="smtp",
            operation="send_email",
            message="boom",
        )


class TestMugenAcpServiceTenantInvitation(unittest.IsolatedAsyncioTestCase):
    """Covers invitation delivery, token handling, resend/revoke, and redeem."""

    async def test_constructor_and_helper_branches(self) -> None:
        config = SimpleNamespace(
            acp=SimpleNamespace(
                argon2=SimpleNamespace(
                    time_cost=1,
                    memory_cost=1024,
                    parallelism=1,
                    hash_len=16,
                ),
                refresh_token_pepper="pepper",
                tenant_invitation_ttl_seconds=0,
                tenant_invitation_invite_base_url="https://invite.example.com/path",
            )
        )
        logger = SimpleNamespace(debug=Mock(), warning=Mock())
        membership_svc = object()
        user_svc = object()
        registry = SimpleNamespace(
            get_resource_by_type=Mock(
                side_effect=lambda edm_type: SimpleNamespace(
                    service_key=f"{edm_type}-svc"
                )
            ),
            get_edm_service=Mock(
                side_effect=lambda service_key: (
                    membership_svc
                    if "TenantMembership" in service_key
                    else user_svc
                )
            ),
        )

        svc = TenantInvitationService(
            table="admin_tenant_invitation",
            rsg=SimpleNamespace(),
            config_provider=lambda: config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )
        self.assertIs(svc._tenant_membership_svc, membership_svc)
        self.assertIs(svc._user_svc, user_svc)
        self.assertEqual(svc._tenant_invitation_ttl_seconds(), 604800)
        self.assertEqual(
            svc._serialize_uuid(uuid.UUID("11111111-1111-1111-1111-111111111111")),
            "11111111-1111-1111-1111-111111111111",
        )

        svc._tenant_membership_svc = None
        svc._user_svc = None
        svc._resolve_related_services()
        self.assertIs(svc._tenant_membership_svc, membership_svc)
        self.assertIs(svc._user_svc, user_svc)

        with patch.object(invitation_mod, "abort", side_effect=_abort_raiser):
            svc._tenant_membership_svc = None
            svc._user_svc = None
            svc._registry_provider = Mock(side_effect=RuntimeError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                svc._resolve_related_services()
            self.assertEqual(ex.exception.code, 500)

            svc._config = SimpleNamespace(acp=SimpleNamespace(tenant_invitation_invite_base_url=""))
            with self.assertRaises(_AbortCalled) as ex:
                svc._tenant_invitation_base_url()
            self.assertEqual(ex.exception.code, 503)

    async def test_create_delivery_policies_and_send_before_persist(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        events: list[str] = []
        gateway = _GatewayOk(events)

        async def _insert_one(_table, values):
            events.append("insert")
            return {
                "id": values["id"],
                "tenant_id": values["tenant_id"],
                "email": values["email"],
                "invited_by_user_id": values.get("invited_by_user_id"),
                "token_hash": values["token_hash"],
                "expires_at": values["expires_at"],
                "accepted_at": None,
                "accepted_by_user_id": None,
                "revoked_at": None,
                "revoked_by_user_id": None,
                "status": values["status"],
                "row_version": 1,
            }

        svc._rsg = SimpleNamespace(insert_one=AsyncMock(side_effect=_insert_one))

        with patch.object(
            invitation_mod.di, "container", new=SimpleNamespace(email_gateway=gateway)
        ):
            created = await TenantInvitationService.create(
                svc,
                {
                    "id": invitation_id,
                    "tenant_id": tenant_id,
                    "email": "invitee@example.com",
                    "invited_by_user_id": uuid.uuid4(),
                },
            )

        self.assertEqual(created.id, invitation_id)
        self.assertEqual(created.status, "invited")
        self.assertEqual(events, ["send", "insert"])
        inserted = svc._rsg.insert_one.await_args.args[1]
        self.assertEqual(inserted["status"], "invited")
        self.assertIn("token_hash", inserted)
        self.assertNotIn("token", inserted)
        self.assertTrue(gateway.requests)

        with (
            patch.object(invitation_mod, "abort", side_effect=_abort_raiser),
            patch.object(
                invitation_mod.di, "container", new=SimpleNamespace(email_gateway=None)
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.create(
                    svc,
                    {
                        "tenant_id": tenant_id,
                        "email": "invitee@example.com",
                    },
                )
            self.assertEqual(ex.exception.code, 503)

        with (
            patch.object(invitation_mod, "abort", side_effect=_abort_raiser),
            patch.object(
                invitation_mod.di,
                "container",
                new=SimpleNamespace(email_gateway=_GatewayFail()),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.create(
                    svc,
                    {
                        "tenant_id": tenant_id,
                        "email": "invitee@example.com",
                    },
                )
            self.assertEqual(ex.exception.code, 502)

    async def test_token_hash_verify_rotation_and_failures(self) -> None:
        svc = _service()
        token = "plain-token"
        token_hash = "stored-hash"
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc._ph = SimpleNamespace(
            verify=Mock(return_value=True),
            check_needs_rehash=Mock(return_value=True),
            hash=Mock(return_value="rehashed"),
        )
        svc.update = AsyncMock(return_value=None)
        self.assertTrue(
            await TenantInvitationService._verify_token_hash(
                svc,
                token_hash=token_hash,
                token=token,
                where=where,
            )
        )
        svc.update.assert_awaited_once()

        svc._ph.check_needs_rehash = Mock(return_value=False)
        self.assertTrue(
            await TenantInvitationService._verify_token_hash(
                svc,
                token_hash=token_hash,
                token=token,
                where=where,
            )
        )

        svc._ph.check_needs_rehash = Mock(return_value=True)
        svc.update = AsyncMock(side_effect=SQLAlchemyError("db"))
        self.assertTrue(
            await TenantInvitationService._verify_token_hash(
                svc,
                token_hash=token_hash,
                token=token,
                where=where,
            )
        )

        svc._ph.verify = Mock(side_effect=VerificationError("bad"))
        self.assertFalse(
            await TenantInvitationService._verify_token_hash(
                svc,
                token_hash=token_hash,
                token="wrong-token",
                where=where,
            )
        )

    async def test_resend_and_revoke_paths(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": invitation_id}
        data = SimpleNamespace(row_version=3)

        invitation = _invitation(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            status="invited",
            row_version=3,
        )
        updated = _invitation(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            status="invited",
            row_version=4,
        )
        svc.get = AsyncMock(return_value=invitation)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._send_invitation_email = AsyncMock(return_value=None)

        metadata = await TenantInvitationService.action_resend(
            svc,
            tenant_id=tenant_id,
            entity_id=invitation_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual(metadata["Status"], "invited")
        self.assertNotIn("Token", metadata)
        self.assertNotIn("TokenHash", metadata)

        svc.update_with_row_version = AsyncMock(return_value=updated)
        payload, status = await TenantInvitationService.action_revoke(
            svc,
            tenant_id=tenant_id,
            entity_id=invitation_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(invitation_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=_invitation(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    status="accepted",
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(return_value=invitation)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            expired = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                status="invited",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            svc.get = AsyncMock(return_value=expired)
            svc.update_with_row_version = AsyncMock(return_value=expired)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

    async def test_send_create_resend_revoke_additional_error_branches(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": invitation_id}
        data = SimpleNamespace(row_version=3)

        with (
            patch.object(invitation_mod, "abort", side_effect=_abort_raiser),
            patch.object(
                invitation_mod.di,
                "container",
                new=SimpleNamespace(
                    email_gateway=SimpleNamespace(
                        send_email=AsyncMock(side_effect=RuntimeError("boom"))
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await svc._send_invitation_email(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    email="invitee@example.com",
                    token="token",
                )
            self.assertEqual(ex.exception.code, 502)

            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.create(
                    svc,
                    {"tenant_id": "bad-uuid", "email": "invitee@example.com"},
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.create(
                    svc,
                    {"tenant_id": tenant_id, "email": "   "},
                )
            self.assertEqual(ex.exception.code, 400)

            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(
                return_value=_invitation(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    status="pending",
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            invited = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                status="invited",
            )
            svc.get = AsyncMock(return_value=invited)
            svc._send_invitation_email = AsyncMock(return_value=None)
            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_resend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            non_invited = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                status="accepted",
            )
            svc.get = AsyncMock(return_value=non_invited)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            expired = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                status="invited",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            svc.get = AsyncMock(return_value=expired)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            unexpired = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                status="invited",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            svc.get = AsyncMock(return_value=unexpired)
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.action_revoke(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=invitation_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_redeem_authenticated_success_and_failures(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": invitation_id}
        now = datetime.now(timezone.utc)
        invitation = _invitation(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            email="member@example.com",
            status="invited",
            row_version=5,
            expires_at=now + timedelta(hours=1),
        )

        svc.get = AsyncMock(return_value=invitation)
        svc._user_svc.get = AsyncMock(
            return_value=SimpleNamespace(id=auth_user_id, login_email="member@example.com")
        )
        svc._verify_token_hash = AsyncMock(return_value=True)
        svc._tenant_membership_svc.get = AsyncMock(return_value=None)
        svc._tenant_membership_svc.create = AsyncMock(return_value=None)
        svc.update_with_row_version = AsyncMock(return_value=SimpleNamespace(id=invitation_id))

        payload, status = await TenantInvitationService.redeem_authenticated(
            svc,
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            auth_user_id=auth_user_id,
            token="token",
        )
        self.assertEqual((payload, status), ("", 204))
        svc._tenant_membership_svc.create.assert_awaited_once()
        svc.update_with_row_version.assert_awaited_once()

        with patch.object(invitation_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=_invitation(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    status="accepted",
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(return_value=invitation)
            svc._user_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=auth_user_id, login_email="other@example.com")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 403)

            svc._user_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=auth_user_id, login_email="member@example.com")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="",
                )
            self.assertEqual(ex.exception.code, 403)

            svc._verify_token_hash = AsyncMock(return_value=False)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 403)

            svc._verify_token_hash = AsyncMock(return_value=True)
            svc.get = AsyncMock(
                return_value=_invitation(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    email="member@example.com",
                    status="invited",
                    row_version=8,
                    expires_at=now - timedelta(seconds=1),
                )
            )
            svc.update_with_row_version = AsyncMock(return_value=SimpleNamespace(id=invitation_id))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(return_value=invitation)
            svc._tenant_membership_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=uuid.uuid4(), status="suspended")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc._tenant_membership_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=uuid.uuid4(), status="active")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            membership = SimpleNamespace(id=uuid.uuid4(), status="invited", row_version=1)
            svc._tenant_membership_svc.get = AsyncMock(return_value=membership)
            svc._tenant_membership_svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc._tenant_membership_svc.update_with_row_version = AsyncMock(
                return_value=SimpleNamespace(id=membership.id)
            )
            svc.update_with_row_version = AsyncMock(side_effect=RowVersionConflict("table"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 404)

            svc._user_svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 401)

    async def test_redeem_authenticated_additional_error_branches(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        invitation_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        invitation = _invitation(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            email="member@example.com",
            status="invited",
            row_version=7,
        )
        svc.get = AsyncMock(return_value=invitation)
        svc._user_svc.get = AsyncMock(
            return_value=SimpleNamespace(id=auth_user_id, login_email="member@example.com")
        )
        svc._verify_token_hash = AsyncMock(return_value=True)
        svc._tenant_membership_svc.get = AsyncMock(return_value=None)
        svc._tenant_membership_svc.create = AsyncMock(return_value=None)
        svc.update_with_row_version = AsyncMock(return_value=SimpleNamespace(id=invitation_id))

        with patch.object(invitation_mod, "abort", side_effect=_abort_raiser):
            svc._tenant_membership_svc = None
            svc._user_svc = None
            svc._resolve_related_services = Mock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc._tenant_membership_svc = SimpleNamespace(
                get=AsyncMock(return_value=None),
                create=AsyncMock(return_value=None),
                update_with_row_version=AsyncMock(return_value=None),
            )
            svc._user_svc = SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(
                        id=auth_user_id, login_email="member@example.com"
                    )
                )
            )
            svc._resolve_related_services = Mock(return_value=None)

            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=invitation)
            svc._user_svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc._user_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=auth_user_id, login_email="member@example.com")
            )
            svc.get = AsyncMock(
                return_value=_invitation(
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    email="member@example.com",
                    status="invited",
                    row_version=7,
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                )
            )
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 404)

            active_invitation = _invitation(
                tenant_id=tenant_id,
                invitation_id=invitation_id,
                email="member@example.com",
                status="invited",
                row_version=7,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            svc.get = AsyncMock(return_value=active_invitation)
            svc._tenant_membership_svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc._tenant_membership_svc.get = AsyncMock(return_value=None)
            svc._tenant_membership_svc.create = AsyncMock(
                side_effect=SQLAlchemyError("db")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            membership = SimpleNamespace(id=uuid.uuid4(), status="invited", row_version=1)
            svc._tenant_membership_svc.get = AsyncMock(return_value=membership)
            svc._tenant_membership_svc.update_with_row_version = AsyncMock(
                side_effect=SQLAlchemyError("db")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)

            svc._tenant_membership_svc.update_with_row_version = AsyncMock(
                return_value=None
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 404)

            svc._tenant_membership_svc.get = AsyncMock(
                return_value=SimpleNamespace(id=uuid.uuid4(), status="unknown")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 409)

            svc._tenant_membership_svc.get = AsyncMock(return_value=None)
            svc._tenant_membership_svc.create = AsyncMock(return_value=None)
            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantInvitationService.redeem_authenticated(
                    svc,
                    tenant_id=tenant_id,
                    invitation_id=invitation_id,
                    auth_user_id=auth_user_id,
                    token="token",
                )
            self.assertEqual(ex.exception.code, 500)
