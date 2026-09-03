"""Builds deterministic governed Knowledge Pack projection documents."""

from __future__ import annotations

__all__ = ["KnowledgeProjectionDocumentBuilder", "PROJECTION_SCHEMA_VERSION"]

from hashlib import sha256
import json
import uuid

from mugen.core.contract.gateway.knowledge import KnowledgeIndexDocument
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    ScalarFilter,
    ScalarFilterOp,
)

PROJECTION_SCHEMA_VERSION = 3
_DOCUMENT_NAMESPACE = uuid.UUID("28702d73-85a3-4c06-b9f3-0f52d250eb9d")
_MAX_SEARCH_ALIASES = 32
_MAX_SEARCH_ALIAS_CHARS = 512


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _checksum(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _search_aliases(attributes: object) -> tuple[str, ...]:
    if not isinstance(attributes, dict) or "search_aliases" not in attributes:
        return ()
    raw_aliases = attributes["search_aliases"]
    if not isinstance(raw_aliases, list):
        raise ValueError("Knowledge entry search_aliases must be a list of strings.")
    if len(raw_aliases) > _MAX_SEARCH_ALIASES:
        raise ValueError(
            f"Knowledge entry search_aliases cannot exceed {_MAX_SEARCH_ALIASES} items."
        )
    aliases: list[str] = []
    for raw_alias in raw_aliases:
        if not isinstance(raw_alias, str):
            raise ValueError("Knowledge entry search_aliases must contain strings.")
        alias = " ".join(raw_alias.strip().split())
        if not alias:
            raise ValueError("Knowledge entry search_aliases cannot contain blanks.")
        if len(alias) > _MAX_SEARCH_ALIAS_CHARS:
            raise ValueError(
                "Knowledge entry search_aliases values cannot exceed "
                f"{_MAX_SEARCH_ALIAS_CHARS} characters."
            )
        aliases.append(alias)
    return tuple(aliases)


def _search_content(entry: dict, content: str) -> str:
    parts = (
        entry.get("title"),
        entry.get("summary"),
        *_search_aliases(entry.get("attributes")),
        content,
    )
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_part in parts:
        if not isinstance(raw_part, str):
            continue
        part = " ".join(raw_part.strip().split())
        key = part.casefold()
        if not part or key in seen:
            continue
        seen.add(key)
        normalized.append(part)
    return "\n".join(normalized)


class KnowledgeProjectionDocumentBuilder:  # pylint: disable=too-few-public-methods
    """Rehydrate active relational rows into deterministic gateway documents."""

    _ENTRY_TABLE = "knowledge_pack_knowledge_entry"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"
    _SCOPE_TABLE = "knowledge_pack_knowledge_scope"

    def __init__(self, rsg: IRelationalStorageGateway) -> None:
        self._rsg = rsg

    # pylint: disable=too-many-locals
    async def build(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
    ) -> tuple[list[KnowledgeIndexDocument], str]:
        """Build one document for every active entry/revision/scope combination."""
        entries = await self._rsg.find_many(
            self._ENTRY_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "knowledge_pack_id": knowledge_pack_id,
                        "knowledge_pack_version_id": knowledge_pack_version_id,
                        "is_active": True,
                    }
                )
            ],
            limit=10_000,
        )
        revisions = await self._rsg.find_many(
            self._REVISION_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "knowledge_pack_version_id": knowledge_pack_version_id,
                    },
                    scalar_filters=[
                        ScalarFilter(
                            field="status",
                            op=ScalarFilterOp.IN,
                            value=["approved", "published", "archived"],
                        )
                    ],
                )
            ],
            limit=20_000,
        )
        scopes = await self._rsg.find_many(
            self._SCOPE_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "knowledge_pack_version_id": knowledge_pack_version_id,
                        "is_active": True,
                    }
                )
            ],
            limit=50_000,
        )

        entries_by_id = {
            entry["id"]: entry for entry in entries if entry.get("id") is not None
        }
        revisions_by_id = {
            revision["id"]: revision
            for revision in revisions
            if revision.get("id") is not None
            and revision.get("knowledge_entry_id") in entries_by_id
        }
        documents: list[KnowledgeIndexDocument] = []
        for scope in scopes:
            revision = revisions_by_id.get(scope.get("knowledge_entry_revision_id"))
            if revision is None:
                continue
            entry = entries_by_id.get(revision.get("knowledge_entry_id"))
            content = revision.get("body")
            if not isinstance(content, str) or not content.strip():
                body_json = revision.get("body_json")
                if not body_json:
                    continue
                content = _canonical_json(body_json)
            document_id = str(
                uuid.uuid5(
                    _DOCUMENT_NAMESPACE,
                    ":".join(
                        (
                            str(tenant_id),
                            str(knowledge_pack_version_id),
                            str(revision["id"]),
                            str(scope["id"]),
                            str(PROJECTION_SCHEMA_VERSION),
                        )
                    ),
                )
            )
            effective_scope = {
                field_name: scope.get(field_name) or revision.get(field_name)
                for field_name in ("channel", "locale", "category")
            }
            effective_scope.update(
                {
                    "service_route_key": scope.get("service_route_key"),
                    "client_profile_key": scope.get("client_profile_key"),
                    "service_profile_id": scope.get("service_profile_id"),
                }
            )
            search_content = _search_content(entry, content)
            content_checksum = _checksum(
                {
                    "content": content,
                    "entry_key": entry.get("entry_key"),
                    "search_content": search_content,
                    "title": entry.get("title"),
                    "scope": effective_scope,
                    "schema": PROJECTION_SCHEMA_VERSION,
                }
            )
            documents.append(
                KnowledgeIndexDocument(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    knowledge_pack_id=knowledge_pack_id,
                    knowledge_pack_version_id=knowledge_pack_version_id,
                    knowledge_entry_id=entry["id"],
                    knowledge_entry_revision_id=revision["id"],
                    knowledge_scope_id=scope["id"],
                    entry_key=str(entry["entry_key"]),
                    title=str(entry["title"]),
                    content=content,
                    content_checksum=content_checksum,
                    projection_schema_version=PROJECTION_SCHEMA_VERSION,
                    search_content=search_content,
                    **effective_scope,
                )
            )
        documents.sort(key=lambda item: item.document_id)
        projection_checksum = _checksum(
            [
                {
                    "document_id": document.document_id,
                    "content_checksum": document.content_checksum,
                }
                for document in documents
            ]
        )
        return documents, projection_checksum
