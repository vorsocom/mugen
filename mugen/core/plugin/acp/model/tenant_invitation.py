"""Provides an ORM for tenant invitations."""

__all__ = ["TenantInvitation"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PGENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


class TenantInvitationStatus(str, enum.Enum):
    """Tenant status enum types."""

    ACCEPTED = "accepted"

    EXPIRED = "expired"

    INVITED = "invited"

    REVOKED = "revoked"


# pylint: disable=too-few-public-methods
class TenantInvitation(ModelBase, TenantScopedMixin):
    """An ORM for tenant invitations."""

    __tablename__ = "admin_tenant_invitation"

    email: Mapped[str] = mapped_column(
        CITEXT(254),
        index=True,
        nullable=False,
    )

    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )

    token_hash: Mapped[str] = mapped_column(
        Text,
        unique=True,
        index=True,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    accepted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )

    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            TenantInvitationStatus,
            name="admin_tenant_invitation_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'invited'"),
    )

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="tenant_invitations",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(email)) > 0",
            name="ck_tenant_invitation__email_nonempty",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL) OR "
            "(status <> 'accepted' AND accepted_at IS NULL)",
            name="ck_tenant_invitation__accepted_at_matches_status",
        ),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL)",
            name="ck_tenant_invitation__revoked_at_matches_status",
        ),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_tenant_invitation__not_accepted_and_revoked",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_tenant_invitation__tenant_id_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"TenantInvitation(id={self.id!r})"
