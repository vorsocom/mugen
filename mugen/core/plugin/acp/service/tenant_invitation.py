"""Provides a service for the TenantInvitation declarative model."""

__all__ = ["TenantInvitationService"]

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.email import EmailGatewayError, EmailSendRequest
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import (
    ITenantInvitationService,
    ITenantMembershipService,
    IUserService,
)
from mugen.core.plugin.acp.domain import TenantInvitationDE

_EDM_TENANT_MEMBERSHIP = "ACP.TenantMembership"
_EDM_USER = "ACP.User"


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class TenantInvitationService(
    IRelationalService[TenantInvitationDE],
    ITenantInvitationService,
):
    """A service for the Tenant declarative model."""

    # pylint: disable=too-many-arguments
    # ylint: disable=too-many-positional-arguments
    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        logger_provider=_logger_provider,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=TenantInvitationDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

        try:
            self._config = config_provider()
        except Exception:  # pylint: disable=broad-exception-caught
            self._config = SimpleNamespace()
        if self._config is None:
            self._config = SimpleNamespace()

        try:
            self._logger = logger_provider()
        except Exception:  # pylint: disable=broad-exception-caught
            self._logger = logging.getLogger(__name__)
        self._registry_provider = registry_provider

        self._tenant_membership_svc: ITenantMembershipService | None = None
        self._user_svc: IUserService | None = None
        try:
            registry: IAdminRegistry = registry_provider()
            self._tenant_membership_svc = registry.get_edm_service(
                registry.get_resource_by_type(_EDM_TENANT_MEMBERSHIP).service_key,
            )
            self._user_svc = registry.get_edm_service(
                registry.get_resource_by_type(_EDM_USER).service_key,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Keep constructor side-effect light for tests that instantiate
            # thin services without wiring ACP runtime dependencies.
            self._tenant_membership_svc = None
            self._user_svc = None

        argon2_cfg = getattr(
            getattr(self._acp_config(), "argon2", None),
            "__dict__",
            {},
        )
        self._ph = PasswordHasher(
            time_cost=int(argon2_cfg.get("time_cost", 3)),
            memory_cost=int(argon2_cfg.get("memory_cost", 65536)),
            parallelism=int(argon2_cfg.get("parallelism", 4)),
            hash_len=int(argon2_cfg.get("hash_len", 32)),
        )

    def _acp_config(self) -> SimpleNamespace:
        return getattr(self._config, "acp", SimpleNamespace())

    def _resolve_related_services(self) -> None:
        if self._tenant_membership_svc is not None and self._user_svc is not None:
            return

        try:
            registry: IAdminRegistry = self._registry_provider()
            self._tenant_membership_svc = registry.get_edm_service(
                registry.get_resource_by_type(_EDM_TENANT_MEMBERSHIP).service_key,
            )
            self._user_svc = registry.get_edm_service(
                registry.get_resource_by_type(_EDM_USER).service_key,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            abort(500)

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    @staticmethod
    def _serialize_uuid(value: uuid.UUID | None) -> str | None:
        if value is None:
            return None
        return str(value)

    def _metadata(self, invitation: TenantInvitationDE) -> dict[str, Any]:
        return {
            "Id": str(invitation.id),
            "TenantId": str(invitation.tenant_id),
            "Email": invitation.email,
            "InvitedByUserId": self._serialize_uuid(invitation.invited_by_user_id),
            "ExpiresAt": self._serialize_datetime(invitation.expires_at),
            "AcceptedAt": self._serialize_datetime(invitation.accepted_at),
            "AcceptedByUserId": self._serialize_uuid(invitation.accepted_by_user_id),
            "RevokedAt": self._serialize_datetime(invitation.revoked_at),
            "RevokedByUserId": self._serialize_uuid(invitation.revoked_by_user_id),
            "Status": invitation.status,
            "RowVersion": invitation.row_version,
        }

    def _tenant_invitation_ttl_seconds(self) -> int:
        ttl = int(getattr(self._acp_config(), "tenant_invitation_ttl_seconds", 604800))
        if ttl <= 0:
            ttl = 604800
        return ttl

    def _tenant_invitation_base_url(self) -> str:
        raw_base_url = getattr(
            self._acp_config(),
            "tenant_invitation_invite_base_url",
            "",
        )
        base_url = str(raw_base_url).strip()
        if not base_url:
            abort(
                503,
                (
                    "Invitation delivery is unavailable because "
                    "acp.tenant_invitation_invite_base_url is not configured."
                ),
            )

        return base_url.rstrip("/")

    def _build_invite_url(
        self,
        *,
        tenant_id: uuid.UUID,
        invitation_id: uuid.UUID,
        token: str,
    ) -> str:
        base_url = self._tenant_invitation_base_url()
        return (
            f"{base_url}/{tenant_id}/{invitation_id}"
            f"?token={quote(token, safe='')}"
        )

    def _generate_token(self) -> str:
        return secrets.token_urlsafe(48)

    def _generate_token_hash(self, token: str) -> str:
        pepper = str(getattr(self._acp_config(), "refresh_token_pepper", ""))
        return self._ph.hash(token + pepper)

    async def _verify_token_hash(
        self,
        *,
        token_hash: str,
        token: str,
        where: Mapping[str, Any],
    ) -> bool:
        pepper = str(getattr(self._acp_config(), "refresh_token_pepper", ""))
        try:
            self._ph.verify(token_hash, token + pepper)
            if self._ph.check_needs_rehash(token_hash):
                try:
                    await self.update(
                        where,
                        {"token_hash": self._generate_token_hash(token)},
                    )
                except SQLAlchemyError:
                    self._logger.debug(
                        "Could not rehash tenant invitation token hash.",
                    )
            return True
        except VerificationError:
            self._logger.debug("Tenant invitation token hash verification failed.")
            return False

    @staticmethod
    def _email_gateway_provider():
        gateway = getattr(di.container, "email_gateway", None)
        if gateway is None:
            abort(
                503,
                (
                    "Invitation delivery is unavailable because no email gateway "
                    "is configured."
                ),
            )
        return gateway

    async def _send_invitation_email(
        self,
        *,
        tenant_id: uuid.UUID,
        invitation_id: uuid.UUID,
        email: str,
        token: str,
    ) -> None:
        invite_url = self._build_invite_url(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            token=token,
        )

        email_gateway = self._email_gateway_provider()
        request = EmailSendRequest(
            to=[email],
            subject="Your tenant invitation",
            text_body=(
                "You have been invited to join a tenant.\n\n"
                f"TenantId: {tenant_id}\n"
                f"InvitationId: {invitation_id}\n"
                f"InviteUrl: {invite_url}\n"
            ),
        )
        try:
            await email_gateway.send_email(request)
        except EmailGatewayError as exc:
            self._logger.warning(
                "Tenant invitation email delivery failed at gateway level."
            )
            self._logger.debug(str(exc))
            abort(502, "Invitation delivery failed.")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logger.warning("Tenant invitation email delivery failed.")
            self._logger.debug(str(exc))
            abort(502, "Invitation delivery failed.")

    async def create(self, values: Mapping[str, Any]) -> TenantInvitationDE:
        token = self._generate_token()
        try:
            raw_invitation_id = values.get("id")
            invitation_id = (
                uuid.uuid4()
                if raw_invitation_id is None
                else uuid.UUID(str(raw_invitation_id))
            )
            tenant_id = uuid.UUID(str(values.get("tenant_id")))
        except (TypeError, ValueError):
            abort(400, "TenantId must be a valid UUID.")

        email = str(values.get("email", "")).strip()
        if not email:
            abort(400, "Email is required.")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._tenant_invitation_ttl_seconds())

        await self._send_invitation_email(
            tenant_id=tenant_id,
            invitation_id=invitation_id,
            email=email,
            token=token,
        )

        create_values = dict(values)
        create_values["id"] = invitation_id
        create_values["email"] = email
        create_values["token_hash"] = self._generate_token_hash(token)
        create_values["expires_at"] = expires_at
        create_values["status"] = "invited"

        return await super().create(create_values)

    async def action_resend(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> dict[str, Any]:
        try:
            invitation = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if invitation is None:
            abort(404, "Tenant invitation not found.")

        if invitation.status in {"accepted", "revoked"}:
            abort(409, "Invitation is in a terminal state and cannot be resent.")

        if invitation.status not in {"invited", "expired"}:
            abort(409, "Invitation cannot be resent from the current status.")

        token = self._generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._tenant_invitation_ttl_seconds(),
        )

        await self._send_invitation_email(
            tenant_id=invitation.tenant_id,
            invitation_id=entity_id,
            email=invitation.email,
            token=token,
        )

        svc: ICrudServiceWithRowVersion[TenantInvitationDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=int(data.row_version),
                changes={
                    "status": "invited",
                    "invited_by_user_id": auth_user_id,
                    "token_hash": self._generate_token_hash(token),
                    "expires_at": expires_at,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return self._metadata(updated)

    async def action_revoke(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        try:
            invitation = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if invitation is None:
            abort(404, "Tenant invitation not found.")

        svc: ICrudServiceWithRowVersion[TenantInvitationDE] = self
        row_version = int(data.row_version)

        now = datetime.now(timezone.utc)
        if invitation.status != "invited":
            abort(409, "Invitation can only be revoked from invited status.")

        if invitation.expires_at <= now:
            try:
                updated = await svc.update_with_row_version(
                    where=where,
                    expected_row_version=row_version,
                    changes={"status": "expired"},
                )
            except RowVersionConflict:
                abort(409, "RowVersion conflict. Refresh and retry.")
            except SQLAlchemyError:
                abort(500)

            if updated is None:
                abort(404, "Update not performed. No row matched.")

            abort(409, "Invitation has expired and can no longer be revoked.")

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=row_version,
                changes={
                    "status": "revoked",
                    "revoked_at": now,
                    "revoked_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def redeem_authenticated(
        self,
        *,
        tenant_id: uuid.UUID,
        invitation_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        token: str,
    ) -> tuple[dict[str, Any], int]:
        self._resolve_related_services()
        user_svc = self._user_svc
        tenant_membership_svc = self._tenant_membership_svc
        if user_svc is None or tenant_membership_svc is None:
            abort(500)

        where = {"tenant_id": tenant_id, "id": invitation_id}
        try:
            invitation = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if invitation is None:
            abort(404, "Tenant invitation not found.")

        if invitation.status != "invited":
            abort(409, "Invitation is no longer redeemable.")

        try:
            user = await user_svc.get({"id": auth_user_id})
        except SQLAlchemyError:
            abort(500)

        if user is None:
            abort(401)

        if user.login_email != invitation.email:
            abort(403, "Authenticated login email does not match invitation email.")

        token_value = token.strip()
        if not token_value:
            abort(403, "Invitation token is invalid.")

        if not await self._verify_token_hash(
            token_hash=invitation.token_hash,
            token=token_value,
            where=where,
        ):
            abort(403, "Invitation token is invalid.")

        now = datetime.now(timezone.utc)
        if invitation.expires_at <= now:
            svc: ICrudServiceWithRowVersion[TenantInvitationDE] = self
            try:
                expired = await svc.update_with_row_version(
                    where=where,
                    expected_row_version=invitation.row_version,
                    changes={"status": "expired"},
                )
            except RowVersionConflict:
                abort(409, "RowVersion conflict. Refresh and retry.")
            except SQLAlchemyError:
                abort(500)

            if expired is None:
                abort(404, "Update not performed. No row matched.")

            abort(409, "Invitation token has expired.")

        try:
            membership = await tenant_membership_svc.get(
                {"tenant_id": tenant_id, "user_id": auth_user_id}
            )
        except SQLAlchemyError:
            abort(500)

        if membership is None:
            try:
                await tenant_membership_svc.create(
                    {
                        "tenant_id": tenant_id,
                        "user_id": auth_user_id,
                        "role_in_tenant": "member",
                        "status": "active",
                        "joined_at": now,
                    }
                )
            except SQLAlchemyError:
                abort(500)
        elif membership.status == "invited":
            membership_svc: ICrudServiceWithRowVersion[Any] = tenant_membership_svc
            try:
                updated_membership = await membership_svc.update_with_row_version(
                    where={"tenant_id": tenant_id, "id": membership.id},
                    expected_row_version=membership.row_version,
                    changes={
                        "status": "active",
                        "joined_at": now,
                    },
                )
            except RowVersionConflict:
                abort(409, "RowVersion conflict. Refresh and retry.")
            except SQLAlchemyError:
                abort(500)

            if updated_membership is None:
                abort(404, "Update not performed. No row matched.")
        elif membership.status == "suspended":
            abort(409, "Suspended memberships cannot redeem invitations.")
        elif membership.status == "active":
            abort(409, "User is already an active tenant member.")
        else:
            abort(409, "Tenant membership is not redeemable from current status.")

        invitation_svc: ICrudServiceWithRowVersion[TenantInvitationDE] = self
        try:
            updated_invitation = await invitation_svc.update_with_row_version(
                where=where,
                expected_row_version=invitation.row_version,
                changes={
                    "status": "accepted",
                    "accepted_at": now,
                    "accepted_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated_invitation is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204
