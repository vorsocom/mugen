"""Provides a CRUD service for blocklist entries and sender block actions."""

__all__ = ["BlocklistEntryService"]

from datetime import datetime, timezone
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.api.validation import (
    BlockSenderActionValidation,
    UnblockSenderActionValidation,
)
from mugen.core.plugin.channel_orchestration.contract.service.blocklist_entry import (
    IBlocklistEntryService,
)
from mugen.core.plugin.channel_orchestration.domain import BlocklistEntryDE
from mugen.core.plugin.channel_orchestration.service.orchestration_event import (
    OrchestrationEventService,
)


class BlocklistEntryService(
    IRelationalService[BlocklistEntryDE],
    IBlocklistEntryService,
):
    """A CRUD service for sender blocklist entries and related actions."""

    _EVENT_TABLE = "channel_orchestration_orchestration_event"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=BlocklistEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._event_service = OrchestrationEventService(
            table=self._EVENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _same_channel_profile(
        entry_channel_profile_id: uuid.UUID | None,
        requested_channel_profile_id: uuid.UUID | None,
    ) -> bool:
        return entry_channel_profile_id == requested_channel_profile_id

    async def _find_active_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        sender_key: str,
        channel_profile_id: uuid.UUID | None,
    ) -> BlocklistEntryDE | None:
        now = self._now_utc()
        rows = await self.list()

        for row in rows:
            if row.tenant_id != tenant_id:
                continue

            if not bool(row.is_active):
                continue

            if (row.sender_key or "").casefold() != sender_key.casefold():
                continue

            if not self._same_channel_profile(
                row.channel_profile_id,
                channel_profile_id,
            ):
                continue

            if row.expires_at is not None and row.expires_at <= now:
                continue

            return row

        return None

    async def action_block_sender(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict,  # noqa: ARG002
        auth_user_id: uuid.UUID,
        data: BlockSenderActionValidation,
    ) -> tuple[dict[str, str], int]:
        """Block sender for tenant/channel intake routes."""
        sender_key = self._normalize_optional_text(data.sender_key)
        if sender_key is None:
            abort(400, "SenderKey must be non-empty.")

        active = await self._find_active_entry(
            tenant_id=tenant_id,
            sender_key=sender_key,
            channel_profile_id=data.channel_profile_id,
        )

        now = self._now_utc()
        if active is None:
            try:
                created = await self.create(
                    {
                        "tenant_id": tenant_id,
                        "channel_profile_id": data.channel_profile_id,
                        "sender_key": sender_key,
                        "reason": self._normalize_optional_text(data.reason),
                        "blocked_at": now,
                        "blocked_by_user_id": auth_user_id,
                        "expires_at": data.expires_at,
                        "is_active": True,
                        "attributes": data.attributes,
                    }
                )
            except SQLAlchemyError:
                abort(500)

            try:
                await self._event_service.create(
                    {
                        "tenant_id": tenant_id,
                        "channel_profile_id": data.channel_profile_id,
                        "sender_key": sender_key,
                        "event_type": "block_sender",
                        "decision": "blocked",
                        "reason": self._normalize_optional_text(data.reason),
                        "actor_user_id": auth_user_id,
                        "occurred_at": now,
                        "source": "channel_orchestration",
                    }
                )
            except SQLAlchemyError:
                abort(500)

            return {"BlocklistEntryId": str(created.id), "Status": "blocked"}, 200

        try:
            updated = await self.update(
                {
                    "tenant_id": tenant_id,
                    "id": active.id,
                },
                {
                    "reason": self._normalize_optional_text(data.reason),
                    "blocked_at": now,
                    "blocked_by_user_id": auth_user_id,
                    "expires_at": data.expires_at,
                    "is_active": True,
                    "unblocked_at": None,
                    "unblocked_by_user_id": None,
                    "unblock_reason": None,
                    "attributes": data.attributes,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Blocklist entry not found.")

        try:
            await self._event_service.create(
                {
                    "tenant_id": tenant_id,
                    "channel_profile_id": data.channel_profile_id,
                    "sender_key": sender_key,
                    "event_type": "block_sender",
                    "decision": "blocked",
                    "reason": self._normalize_optional_text(data.reason),
                    "actor_user_id": auth_user_id,
                    "occurred_at": now,
                    "source": "channel_orchestration",
                }
            )
        except SQLAlchemyError:
            abort(500)

        return {"BlocklistEntryId": str(updated.id), "Status": "blocked"}, 200

    async def action_unblock_sender(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict,  # noqa: ARG002
        auth_user_id: uuid.UUID,
        data: UnblockSenderActionValidation,
    ) -> tuple[dict[str, str], int]:
        """Unblock sender for tenant/channel intake routes."""
        sender_key = self._normalize_optional_text(data.sender_key)
        if sender_key is None:
            abort(400, "SenderKey must be non-empty.")

        active = await self._find_active_entry(
            tenant_id=tenant_id,
            sender_key=sender_key,
            channel_profile_id=data.channel_profile_id,
        )

        if active is None:
            abort(404, "Active blocklist entry not found.")

        now = self._now_utc()
        try:
            updated = await self.update(
                {
                    "tenant_id": tenant_id,
                    "id": active.id,
                },
                {
                    "is_active": False,
                    "unblocked_at": now,
                    "unblocked_by_user_id": auth_user_id,
                    "unblock_reason": self._normalize_optional_text(data.reason),
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Blocklist entry not found.")

        try:
            await self._event_service.create(
                {
                    "tenant_id": tenant_id,
                    "channel_profile_id": data.channel_profile_id,
                    "sender_key": sender_key,
                    "event_type": "unblock_sender",
                    "decision": "unblocked",
                    "reason": self._normalize_optional_text(data.reason),
                    "actor_user_id": auth_user_id,
                    "occurred_at": now,
                    "source": "channel_orchestration",
                }
            )
        except SQLAlchemyError:
            abort(500)

        return {"BlocklistEntryId": str(updated.id), "Status": "unblocked"}, 200
