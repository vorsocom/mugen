"""Provides an ORM for evidence blob metadata records."""

__all__ = ["EvidenceBlob"]

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Uuid
from sqlalchemy import UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class EvidenceBlob(ModelBase):
    """Metadata-first evidence object for chain-of-custody workflows."""

    __tablename__ = "audit_evidence_blob"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    source_plugin: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    subject_namespace: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    storage_uri: Mapped[str] = mapped_column(
        CITEXT(512),
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    hash_alg: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'sha256'"),
    )

    content_length: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    immutability: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'immutable'"),
    )

    verification_status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'pending'"),
        index=True,
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    redaction_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    redaction_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    legal_hold_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    legal_hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    legal_hold_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    legal_hold_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    legal_hold_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    legal_hold_released_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    legal_hold_release_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    tombstoned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    tombstone_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    purge_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    purged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    purge_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_audit_evidence_blob__trace_id_nonempty_if_set",
        ),
        CheckConstraint(
            "source_plugin IS NULL OR length(btrim(source_plugin)) > 0",
            name="ck_audit_evidence_blob__source_plugin_nonempty_if_set",
        ),
        CheckConstraint(
            "subject_namespace IS NULL OR length(btrim(subject_namespace)) > 0",
            name="ck_audit_evidence_blob__subject_namespace_nonempty_if_set",
        ),
        CheckConstraint(
            "length(btrim(storage_uri)) > 0",
            name="ck_audit_evidence_blob__storage_uri_nonempty",
        ),
        CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_audit_evidence_blob__content_hash_nonempty",
        ),
        CheckConstraint(
            "length(btrim(hash_alg)) > 0",
            name="ck_audit_evidence_blob__hash_alg_nonempty",
        ),
        CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_audit_evidence_blob__content_length_nonnegative",
        ),
        CheckConstraint(
            "immutability IN ('immutable', 'mutable')",
            name="ck_audit_evidence_blob__immutability_valid",
        ),
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'failed')",
            name="ck_audit_evidence_blob__verification_status_valid",
        ),
        CheckConstraint(
            "redaction_reason IS NULL OR length(btrim(redaction_reason)) > 0",
            name="ck_audit_evidence_blob__redaction_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "legal_hold_reason IS NULL OR length(btrim(legal_hold_reason)) > 0",
            name="ck_audit_evidence_blob__legal_hold_reason_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "legal_hold_release_reason IS NULL OR"
                " length(btrim(legal_hold_release_reason)) > 0"
            ),
            name="ck_audit_evidence_blob__hold_release_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "tombstone_reason IS NULL OR length(btrim(tombstone_reason)) > 0",
            name="ck_audit_evidence_blob__tombstone_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "purge_reason IS NULL OR length(btrim(purge_reason)) > 0",
            name="ck_audit_evidence_blob__purge_reason_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_audit_evidence_blob__tenant_id_id",
        ),
        Index(
            "ix_audit_evidence_blob__tenant_trace",
            "tenant_id",
            "trace_id",
        ),
        Index(
            "ix_audit_evidence_blob__tenant_content_hash",
            "tenant_id",
            "content_hash",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"EvidenceBlob(id={self.id!r})"
