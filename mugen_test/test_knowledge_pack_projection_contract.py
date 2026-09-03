"""Tests governed Knowledge Pack contracts, queues, and safe retrieval."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeDeleteSelector,
    KnowledgeGatewayWriteResult,
    KnowledgeIndexDocument,
    KnowledgeSearchHit,
    KnowledgeSearchQuery,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.gateway.knowledge.common import (
    apply_query_scope,
    document_metadata,
    selector_metadata,
)
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgeIndexProjectionRetryValidation,
)
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryDE,
    KnowledgeEntryRevisionDE,
    KnowledgeIndexProjectionDE,
    KnowledgeScopeDE,
)
from mugen.core.plugin.knowledge_pack.model import (
    KnowledgeIndexProjection,
    KnowledgeScope,
)
from mugen.core.plugin.knowledge_pack.runtime import (
    configure_knowledge_gateway,
    get_knowledge_gateway,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry import (
    KnowledgeEntryService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_index_projection import (
    KnowledgeIndexProjectionService,
    projection_action_response,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import (
    KnowledgeScopeService,
)
from mugen.core.plugin.knowledge_pack.service.projection_document import (
    PROJECTION_SCHEMA_VERSION,
    KnowledgeProjectionDocumentBuilder,
)
from mugen.core.plugin.knowledge_pack.service.projection_guard import (
    KnowledgeProjectionMutationGuard,
)
from mugen.core.plugin.knowledge_pack.service.retrieval import (
    KnowledgeRetrievalService,
)


def _ids() -> dict[str, uuid.UUID]:
    return {
        name: uuid.uuid4()
        for name in ("tenant", "pack", "version", "entry", "revision", "scope")
    }


def _document(ids: dict[str, uuid.UUID] | None = None) -> KnowledgeIndexDocument:
    values = ids or _ids()
    return KnowledgeIndexDocument(
        document_id=str(uuid.uuid4()),
        tenant_id=values["tenant"],
        knowledge_pack_id=values["pack"],
        knowledge_pack_version_id=values["version"],
        knowledge_entry_id=values["entry"],
        knowledge_entry_revision_id=values["revision"],
        knowledge_scope_id=values["scope"],
        entry_key="refund",
        title="Refund policy",
        content="Approved refund content",
        content_checksum="a" * 64,
        projection_schema_version=PROJECTION_SCHEMA_VERSION,
        channel="web",
        locale="en-US",
        category="billing",
        service_route_key="support",
        client_profile_key="retail",
    )


class _Gateway(IKnowledgeGateway):
    def __init__(self, result: KnowledgeSearchResult | None = None) -> None:
        self.result = result or KnowledgeSearchResult()

    async def check_readiness(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def search(self, query: KnowledgeSearchQuery) -> KnowledgeSearchResult:
        _ = query
        return self.result


class _WritableGateway(_Gateway):
    async def upsert_documents(
        self, documents: list[KnowledgeIndexDocument]
    ) -> KnowledgeGatewayWriteResult:
        return KnowledgeGatewayWriteResult("gateway", len(documents), len(documents))

    async def delete_documents(
        self, selector: KnowledgeDeleteSelector
    ) -> KnowledgeGatewayWriteResult:
        return KnowledgeGatewayWriteResult(
            "gateway", len(selector.document_ids), len(selector.document_ids)
        )


class TestKnowledgeGatewayContracts(unittest.IsolatedAsyncioTestCase):
    """Covers neutral DTO validation, mapping compatibility, and scope ranking."""

    def test_query_document_selector_and_hit_contracts(self) -> None:
        ids = _ids()
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="  refunds  ",
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
            channel=" web ",
            locale="en-US",
            candidate_limit=2,
            min_similarity=0.5,
        )
        self.assertEqual(query.query_text, "refunds")
        self.assertEqual(query.search_term, "refunds")
        self.assertEqual(query.top_k, 2)

        document = _document(ids)
        self.assertEqual(document.index_content, document.content)
        legacy_positional_values = [
            getattr(document, field.name)
            for field in document.__dataclass_fields__.values()
            if field.name != "search_content"
        ]
        self.assertEqual(
            KnowledgeIndexDocument(*legacy_positional_values),  # type: ignore[arg-type]
            document,
        )
        search_document = KnowledgeIndexDocument(
            **{
                field.name: getattr(document, field.name)
                for field in document.__dataclass_fields__.values()
                if field.name != "search_content"
            },
            search_content="  customer search wording  ",
        )
        self.assertEqual(search_document.index_content, "customer search wording")
        blank_search_document = KnowledgeIndexDocument(
            **{
                field.name: getattr(document, field.name)
                for field in document.__dataclass_fields__.values()
                if field.name != "search_content"
            },
            search_content="  ",
        )
        self.assertEqual(blank_search_document.index_content, document.content)
        metadata = document_metadata(document)
        self.assertEqual(metadata["tenant_id"], str(ids["tenant"]))
        self.assertNotIn("search_content", metadata)
        selector = KnowledgeDeleteSelector(
            tenant_id=ids["tenant"],
            knowledge_pack_id=ids["pack"],
            document_ids=(document.document_id, document.document_id, ""),
        )
        self.assertEqual(selector.document_ids, (document.document_id,))
        self.assertEqual(
            selector_metadata(selector)["knowledge_pack_id"], str(ids["pack"])
        )

        hit = KnowledgeSearchHit.from_mapping(
            {
                **metadata,
                "similarity": 0.9,
                "distance": 0.1,
                "snippet": "trailing ",
            }
        )
        self.assertEqual(hit["tenant_id"], str(ids["tenant"]))
        self.assertEqual(hit["snippet"], "trailing ")
        self.assertEqual(len(hit), len(dict(hit)))
        self.assertEqual(hit, dict(hit))
        self.assertEqual(hit, KnowledgeSearchHit.from_mapping(dict(hit)))
        self.assertNotEqual(hit, object())
        self.assertEqual(hit.scope_specificity(query), 2)
        minimal_hit = KnowledgeSearchHit.from_mapping(
            {
                "tenant_id": str(ids["tenant"]),
                "knowledge_pack_version_id": str(ids["version"]),
                "knowledge_entry_revision_id": str(ids["revision"]),
            }
        )
        self.assertIsNone(minimal_hit.knowledge_pack_id)
        result = KnowledgeSearchResult(items=[metadata, hit])
        self.assertEqual(len(result.items), 2)

        service_profile_id = uuid.uuid4()
        profile_query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refunds",
            service_profile_id=service_profile_id,
        )
        profile_document = KnowledgeIndexDocument(
            **{
                field.name: getattr(document, field.name)
                for field in document.__dataclass_fields__.values()
                if field.name != "service_profile_id"
            },
            service_profile_id=service_profile_id,
        )
        profile_hit = KnowledgeSearchHit.from_mapping(profile_document.metadata())
        self.assertEqual(profile_hit.service_profile_id, service_profile_id)
        self.assertEqual(profile_hit.scope_specificity(profile_query), 1)

    def test_contract_validation_errors(self) -> None:
        tenant_id = uuid.uuid4()
        invalid_queries = (
            {"tenant_id": "bad", "query_text": "x"},
            {"tenant_id": tenant_id, "query_text": " "},
            {"tenant_id": tenant_id, "query_text": "x", "candidate_limit": 0},
            {"tenant_id": tenant_id, "query_text": "x", "min_similarity": 2},
            {
                "tenant_id": tenant_id,
                "query_text": "x",
                "knowledge_pack_id": "bad",
            },
            {
                "tenant_id": tenant_id,
                "query_text": "x",
                "service_profile_id": "bad",
            },
        )
        for kwargs in invalid_queries:
            with self.subTest(kwargs=kwargs), self.assertRaises(
                (TypeError, ValueError)
            ):
                KnowledgeSearchQuery(**kwargs)  # type: ignore[arg-type]

        ids = _ids()
        with self.assertRaises(ValueError):
            KnowledgeDeleteSelector(tenant_id=tenant_id)
        with self.assertRaises(TypeError):
            KnowledgeDeleteSelector(
                tenant_id="bad",  # type: ignore[arg-type]
                document_ids=("x",),
            )
        document = _document(ids)
        for field_name, value in (
            ("document_id", ""),
            ("tenant_id", "bad"),
            ("content", ""),
            ("projection_schema_version", 0),
        ):
            kwargs = {
                field.name: getattr(document, field.name)
                for field in document.__dataclass_fields__.values()
            }
            kwargs[field_name] = value
            with self.subTest(field=field_name), self.assertRaises(
                (TypeError, ValueError)
            ):
                KnowledgeIndexDocument(**kwargs)
        with self.assertRaises(ValueError):
            KnowledgeSearchHit.from_mapping({})

    async def test_default_write_methods_and_fingerprint(self) -> None:
        gateway = _Gateway()
        self.assertEqual(gateway.provider_name, "_gateway")
        self.assertEqual(len(gateway.configuration_fingerprint()), 64)
        with self.assertRaises(NotImplementedError):
            await gateway.upsert_documents([])
        with self.assertRaises(NotImplementedError):
            await gateway.delete_documents(
                KnowledgeDeleteSelector(tenant_id=uuid.uuid4(), document_ids=("x",))
            )

    def test_apply_query_scope_exact_precedence_and_wildcards(self) -> None:
        ids = _ids()
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
            channel="web",
            service_route_key="support",
            candidate_limit=2,
        )

        def hit(channel, route, similarity, *, pack_id=None):
            metadata = _document(ids).metadata()
            metadata.update(
                {
                    "channel": channel,
                    "service_route_key": route,
                    "similarity": similarity,
                    "knowledge_pack_id": str(pack_id or ids["pack"]),
                }
            )
            return metadata

        ranked = apply_query_scope(
            [
                hit(None, None, 0.99),
                hit("web", "support", 0.8),
                hit("voice", "support", 1.0),
                hit("web", "support", 1.0, pack_id=uuid.uuid4()),
            ],
            query,
        )
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].channel, "web")
        self.assertEqual(ranked[1].channel, None)

        version_only = KnowledgeDeleteSelector(
            tenant_id=ids["tenant"],
            knowledge_pack_version_id=ids["version"],
        )
        self.assertNotIn("knowledge_pack_id", selector_metadata(version_only))
        self.assertIn("knowledge_pack_version_id", selector_metadata(version_only))
        wrong_version = hit("web", "support", 1.0)
        wrong_version["knowledge_pack_version_id"] = str(uuid.uuid4())
        self.assertEqual(apply_query_scope([wrong_version], query), [])

    def test_service_profile_scope_requires_exact_or_wildcard(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            service_profile_id=service_profile_id,
            candidate_limit=10,
        )

        def metadata(profile_id, similarity):
            values = _document(ids).metadata()
            values["service_profile_id"] = (
                None if profile_id is None else str(profile_id)
            )
            values["similarity"] = similarity
            return values

        exact, wildcard = apply_query_scope(
            [
                metadata(None, 0.99),
                metadata(service_profile_id, 0.8),
                metadata(uuid.uuid4(), 1.0),
            ],
            query,
        )
        self.assertEqual(exact.service_profile_id, service_profile_id)
        self.assertIsNone(wildcard.service_profile_id)

        unscoped = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
        )
        self.assertEqual(
            apply_query_scope([metadata(service_profile_id, 1.0)], unscoped),
            [],
        )


class TestProjectionDocumentsAndQueue(unittest.IsolatedAsyncioTestCase):
    """Covers deterministic relational document building and durable queue actions."""

    async def test_document_builder_is_deterministic_and_filters_ineligible_rows(
        self,
    ) -> None:
        ids = _ids()
        second_entry = uuid.uuid4()
        second_revision = uuid.uuid4()
        second_scope = uuid.uuid4()
        rsg = Mock()
        rsg.find_many = AsyncMock(
            side_effect=[
                [
                    {
                        "id": ids["entry"],
                        "entry_key": "refund",
                        "title": "  Refund policy  ",
                        "summary": "How   refunds work",
                        "attributes": {
                            "search_aliases": [
                                " When can I return payment? ",
                                "refund POLICY",
                                "How refunds work",
                                "Approved   content",
                                "When can I return payment?",
                            ]
                        },
                    },
                    {
                        "id": second_entry,
                        "entry_key": "json",
                        "title": "JSON",
                        "summary": "   ",
                        "attributes": {},
                    },
                    {"id": None},
                ],
                [
                    {
                        "id": ids["revision"],
                        "knowledge_entry_id": ids["entry"],
                        "body": "Approved content",
                        "body_json": None,
                        "channel": "web",
                        "locale": None,
                        "category": "billing",
                    },
                    {
                        "id": second_revision,
                        "knowledge_entry_id": second_entry,
                        "body": None,
                        "body_json": {"answer": "yes"},
                    },
                    {
                        "id": uuid.UUID(int=1),
                        "knowledge_entry_id": ids["entry"],
                        "body": None,
                        "body_json": None,
                    },
                    {"id": uuid.uuid4(), "knowledge_entry_id": uuid.uuid4()},
                ],
                [
                    {
                        "id": ids["scope"],
                        "knowledge_entry_revision_id": ids["revision"],
                        "channel": None,
                        "locale": "en-US",
                        "category": None,
                        "service_route_key": "support",
                        "client_profile_key": None,
                        "service_profile_id": ids["pack"],
                    },
                    {
                        "id": second_scope,
                        "knowledge_entry_revision_id": second_revision,
                    },
                    {
                        "id": uuid.UUID(int=2),
                        "knowledge_entry_revision_id": uuid.UUID(int=1),
                    },
                    {"id": uuid.uuid4(), "knowledge_entry_revision_id": uuid.uuid4()},
                ],
            ]
        )
        builder = KnowledgeProjectionDocumentBuilder(rsg)
        documents, checksum = await builder.build(
            tenant_id=ids["tenant"],
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
        )
        self.assertEqual(len(documents), 2)
        self.assertEqual(len(checksum), 64)
        refund = next(item for item in documents if item.entry_key == "refund")
        self.assertEqual(refund.channel, "web")
        self.assertEqual(refund.locale, "en-US")
        self.assertEqual(refund.service_route_key, "support")
        self.assertEqual(refund.service_profile_id, ids["pack"])
        self.assertEqual(PROJECTION_SCHEMA_VERSION, 3)
        self.assertEqual(
            refund.search_content,
            "Refund policy\nHow refunds work\nWhen can I return payment?\n"
            "Approved content",
        )
        self.assertEqual(refund.content, "Approved content")
        self.assertIn(
            '"answer":"yes"',
            next(item for item in documents if item.entry_key == "json").content,
        )

    async def test_document_checksums_track_title_summary_and_aliases(self) -> None:
        """Retrieval inputs participate in document and projection checksums."""
        ids = _ids()

        async def build(**entry_changes):
            entry = {
                "id": ids["entry"],
                "entry_key": "hours",
                "title": "Opening hours",
                "summary": "Times we are open",
                "attributes": {"search_aliases": ["When are you open?"]},
                **entry_changes,
            }
            rsg = Mock()
            rsg.find_many = AsyncMock(
                side_effect=[
                    [entry],
                    [
                        {
                            "id": ids["revision"],
                            "knowledge_entry_id": ids["entry"],
                            "body": "Open from 09:00 to 17:00.",
                        }
                    ],
                    [
                        {
                            "id": ids["scope"],
                            "knowledge_entry_revision_id": ids["revision"],
                        }
                    ],
                ]
            )
            documents, projection_checksum = await KnowledgeProjectionDocumentBuilder(
                rsg
            ).build(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
            )
            return documents[0].content_checksum, projection_checksum

        baseline = await build()
        variants = (
            await build(title="Business hours"),
            await build(summary="Our weekly schedule"),
            await build(summary=None),
            await build(attributes={"search_aliases": ["What are your hours?"]}),
        )
        for variant in variants:
            with self.subTest(checksum=variant):
                self.assertNotEqual(variant[0], baseline[0])
                self.assertNotEqual(variant[1], baseline[1])

    async def test_document_builder_rejects_invalid_search_aliases(self) -> None:
        """Projection fails closed when governed retrieval aliases are malformed."""
        ids = _ids()
        invalid_aliases = (
            "When are you open?",
            ["valid", 7],
            ["valid", "   "],
            ["x" * 513],
            [f"alias {index}" for index in range(33)],
        )
        for search_aliases in invalid_aliases:
            rsg = Mock()
            rsg.find_many = AsyncMock(
                side_effect=[
                    [
                        {
                            "id": ids["entry"],
                            "entry_key": "hours",
                            "title": "Opening hours",
                            "attributes": {"search_aliases": search_aliases},
                        }
                    ],
                    [
                        {
                            "id": ids["revision"],
                            "knowledge_entry_id": ids["entry"],
                            "body": "Open from 09:00 to 17:00.",
                        }
                    ],
                    [
                        {
                            "id": ids["scope"],
                            "knowledge_entry_revision_id": ids["revision"],
                        }
                    ],
                ]
            )
            with self.subTest(search_aliases=search_aliases), self.assertRaisesRegex(
                ValueError, "search_aliases"
            ):
                await KnowledgeProjectionDocumentBuilder(rsg).build(
                    tenant_id=ids["tenant"],
                    knowledge_pack_id=ids["pack"],
                    knowledge_pack_version_id=ids["version"],
                )

    async def test_invalid_aliases_do_not_queue_a_projection(self) -> None:
        """Malformed aliases fail before a publish projection row is created."""
        ids = _ids()
        service = KnowledgeIndexProjectionService(
            table="knowledge_pack_knowledge_index_projection",
            rsg=Mock(),
            gateway_provider=lambda: _WritableGateway(),
        )
        service.list = AsyncMock(return_value=[])
        service.create = AsyncMock()
        service._document_builder.build = AsyncMock(  # pylint: disable=protected-access
            side_effect=ValueError(
                "Knowledge entry search_aliases cannot contain blanks."
            )
        )
        with self.assertRaisesRegex(ValueError, "search_aliases"):
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="publish",
            )
        service.create.assert_not_awaited()

    async def test_runtime_queue_success_duplicate_cleanup_and_errors(self) -> None:
        ids = _ids()
        gateway = _WritableGateway()
        service = KnowledgeIndexProjectionService(
            table="knowledge_pack_knowledge_index_projection",
            rsg=Mock(),
            gateway_provider=lambda: gateway,
        )
        service.list = AsyncMock(return_value=[])
        service.create = AsyncMock(
            return_value=KnowledgeIndexProjectionDE(
                id=uuid.uuid4(),
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                provider=gateway.provider_name,
                target_fingerprint=gateway.configuration_fingerprint(),
                status="queued",
            )
        )
        service._document_builder.build = AsyncMock(  # pylint: disable=protected-access
            return_value=([_document(ids)], "b" * 64)
        )
        queued = await service.queue_projection(
            tenant_id=ids["tenant"],
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
            requested_by_user_id=uuid.uuid4(),
            operation="publish",
            note=" publish ",
        )
        self.assertEqual(queued.status, "queued")
        self.assertEqual(service.create.await_args.args[0]["document_count"], 1)
        self.assertEqual(
            projection_action_response(queued)["ProjectionId"], str(queued.id)
        )

        active = KnowledgeIndexProjectionDE(id=uuid.uuid4(), status="processing")
        service.list = AsyncMock(return_value=[active])
        self.assertIs(
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="reindex",
            ),
            active,
        )

        service.list = AsyncMock(return_value=[])
        service.create.reset_mock()
        await service.queue_projection(
            tenant_id=ids["tenant"],
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
            requested_by_user_id=uuid.uuid4(),
            operation="cleanup",
        )
        self.assertEqual(service.create.await_args.args[0]["document_count"], 0)

        no_gateway = KnowledgeIndexProjectionService(
            table="p", rsg=Mock(), gateway_provider=lambda: None
        )
        with self.assertRaises(HTTPException) as ctx:
            await no_gateway.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="publish",
            )
        self.assertEqual(ctx.exception.code, 409)

        service.list = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as ctx:
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="publish",
            )
        self.assertEqual(ctx.exception.code, 500)

        service.list = AsyncMock(return_value=[])
        service._document_builder.build = AsyncMock(  # pylint: disable=protected-access
            side_effect=SQLAlchemyError("build")
        )
        with self.assertRaises(HTTPException) as ctx:
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="publish",
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_projection_queue_integrity_and_storage_failures(self) -> None:
        ids = _ids()
        gateway = _WritableGateway()
        service = KnowledgeIndexProjectionService(
            table="p", rsg=Mock(), gateway_provider=lambda: gateway
        )
        service._document_builder.build = AsyncMock(  # pylint: disable=protected-access
            return_value=([], "c" * 64)
        )
        active = KnowledgeIndexProjectionDE(id=uuid.uuid4(), status="queued")

        service.list = AsyncMock(side_effect=[[], [active]])
        service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, RuntimeError("duplicate"))
        )
        self.assertIs(
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="reindex",
            ),
            active,
        )

        service.list = AsyncMock(side_effect=[[], []])
        with self.assertRaises(HTTPException) as ctx:
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="reindex",
            )
        self.assertEqual(ctx.exception.code, 409)

        service.list = AsyncMock(side_effect=[[], SQLAlchemyError("lookup")])
        with self.assertRaises(HTTPException) as ctx:
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="reindex",
            )
        self.assertEqual(ctx.exception.code, 500)

        service.list = AsyncMock(return_value=[])
        service.create = AsyncMock(side_effect=SQLAlchemyError("insert"))
        with self.assertRaises(HTTPException) as ctx:
            await service.queue_projection(
                tenant_id=ids["tenant"],
                knowledge_pack_id=ids["pack"],
                knowledge_pack_version_id=ids["version"],
                requested_by_user_id=uuid.uuid4(),
                operation="reindex",
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_projection_retry_guards_and_success(self) -> None:
        ids = _ids()
        projection_id = uuid.uuid4()
        gateway = _WritableGateway()
        service = KnowledgeIndexProjectionService(
            table="p", rsg=Mock(), gateway_provider=lambda: gateway
        )
        current = KnowledgeIndexProjectionDE(
            id=projection_id,
            tenant_id=ids["tenant"],
            knowledge_pack_version_id=ids["version"],
            provider=gateway.provider_name,
            target_fingerprint=gateway.configuration_fingerprint(),
            status="failed",
            attempt_count=1,
            max_attempts=3,
            row_version=2,
        )
        service.get = AsyncMock(return_value=current)
        service.update_with_row_version = AsyncMock(
            return_value=KnowledgeIndexProjectionDE(
                **{**current.__dict__, "status": "queued"}
            )
        )
        result, status = await service.action_retry(
            tenant_id=ids["tenant"],
            entity_id=projection_id,
            where={"tenant_id": ids["tenant"], "id": projection_id},
            auth_user_id=uuid.uuid4(),
            data=KnowledgeIndexProjectionRetryValidation(row_version=2),
        )
        self.assertEqual(status, 202)
        self.assertEqual(result["Status"], "queued")

        for changed, message in (
            ({"status": "ready"}, "Only failed"),
            ({"status": "cancelled"}, "Only failed"),
            ({"attempt_count": 3}, "retry limit"),
            ({"provider": "changed"}, "provider target changed"),
        ):
            variant = KnowledgeIndexProjectionDE(**{**current.__dict__, **changed})
            service.get = AsyncMock(return_value=variant)
            with self.subTest(changed=changed), self.assertRaisesRegex(
                HTTPException, message
            ):
                await service.action_retry(
                    tenant_id=ids["tenant"],
                    entity_id=projection_id,
                    where={"id": projection_id},
                    auth_user_id=uuid.uuid4(),
                    data=KnowledgeIndexProjectionRetryValidation(row_version=2),
                )

    async def test_projection_retry_storage_rowversion_and_gateway_failures(
        self,
    ) -> None:
        ids = _ids()
        projection_id = uuid.uuid4()
        gateway = _WritableGateway()
        current = KnowledgeIndexProjectionDE(
            id=projection_id,
            tenant_id=ids["tenant"],
            knowledge_pack_version_id=ids["version"],
            provider=gateway.provider_name,
            target_fingerprint=gateway.configuration_fingerprint(),
            status="failed",
            attempt_count=1,
            max_attempts=3,
            row_version=2,
        )
        service = KnowledgeIndexProjectionService(
            table="p", rsg=Mock(), gateway_provider=lambda: gateway
        )
        kwargs = {
            "tenant_id": ids["tenant"],
            "entity_id": projection_id,
            "where": {"tenant_id": ids["tenant"], "id": projection_id},
            "auth_user_id": uuid.uuid4(),
            "data": KnowledgeIndexProjectionRetryValidation(row_version=2),
        }

        for side_effect, expected_code in (
            ([None, None], 404),
            ([None, current], 409),
        ):
            service.get = AsyncMock(side_effect=side_effect)
            with self.subTest(expected_code=expected_code), self.assertRaises(
                HTTPException
            ) as ctx:
                await service.action_retry(**kwargs)
            self.assertEqual(ctx.exception.code, expected_code)

        service.get = AsyncMock(side_effect=SQLAlchemyError("read"))
        with self.assertRaises(HTTPException) as ctx:
            await service.action_retry(**kwargs)
        self.assertEqual(ctx.exception.code, 500)

        no_gateway = KnowledgeIndexProjectionService(
            table="p", rsg=Mock(), gateway_provider=lambda: None
        )
        no_gateway.get = AsyncMock(return_value=current)
        with self.assertRaises(HTTPException) as ctx:
            await no_gateway.action_retry(**kwargs)
        self.assertEqual(ctx.exception.code, 409)

        for side_effect, expected_code in (
            (RowVersionConflict("p"), 409),
            (SQLAlchemyError("update"), 500),
        ):
            service.get = AsyncMock(return_value=current)
            service.update_with_row_version = AsyncMock(side_effect=side_effect)
            with self.subTest(expected_code=expected_code), self.assertRaises(
                HTTPException
            ) as ctx:
                await service.action_retry(**kwargs)
            self.assertEqual(ctx.exception.code, expected_code)

        service.get = AsyncMock(return_value=current)
        service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await service.action_retry(**kwargs)
        self.assertEqual(ctx.exception.code, 404)

    async def test_projection_mutation_guard_and_services(self) -> None:
        ids = _ids()
        rsg = Mock()
        rsg.find_many = AsyncMock(return_value=[])
        guard = KnowledgeProjectionMutationGuard(rsg)
        await guard.assert_mutable(
            tenant_id=ids["tenant"], knowledge_pack_version_id=ids["version"]
        )
        rsg.find_many = AsyncMock(return_value=[{"id": uuid.uuid4()}])
        with self.assertRaises(HTTPException) as ctx:
            await guard.assert_mutable(
                tenant_id=ids["tenant"], knowledge_pack_version_id=ids["version"]
            )
        self.assertEqual(ctx.exception.code, 409)
        rsg.find_many = AsyncMock(side_effect=SQLAlchemyError("db"))
        with self.assertRaises(HTTPException) as ctx:
            await guard.assert_mutable(
                tenant_id=ids["tenant"], knowledge_pack_version_id=ids["version"]
            )
        self.assertEqual(ctx.exception.code, 500)

        for service, current in (
            (
                KnowledgeEntryService("entry", Mock()),
                KnowledgeEntryDE(
                    id=ids["entry"],
                    tenant_id=ids["tenant"],
                    knowledge_pack_version_id=ids["version"],
                ),
            ),
            (
                KnowledgeScopeService("scope", Mock()),
                KnowledgeScopeDE(
                    id=ids["scope"],
                    tenant_id=ids["tenant"],
                    knowledge_pack_version_id=ids["version"],
                ),
            ),
        ):
            service._projection_guard.assert_mutable = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service.get = AsyncMock(return_value=current)
            service._rsg.insert_one = AsyncMock(
                return_value={"id": current.id}
            )  # pylint: disable=protected-access
            service._rsg.update_one = AsyncMock(
                return_value={"id": current.id}
            )  # pylint: disable=protected-access
            await service.create(
                {
                    "tenant_id": ids["tenant"],
                    "knowledge_pack_version_id": ids["version"],
                }
            )
            await service.update_with_row_version(
                {"id": current.id}, expected_row_version=1, changes={"x": 1}
            )
            self.assertGreaterEqual(
                service._projection_guard.assert_mutable.await_count,
                2,  # pylint: disable=protected-access
            )
            service.get = AsyncMock(return_value=None)
            self.assertIsNone(
                await service.update_with_row_version(
                    {"id": current.id}, expected_row_version=1, changes={"x": 1}
                )
            )
            service.get = AsyncMock(return_value=type(current)())
            self.assertIsNone(
                await service.update_with_row_version(
                    {"id": current.id}, expected_row_version=1, changes={"x": 1}
                )
            )

        revision_service = KnowledgeEntryRevisionService("revision", Mock())
        revision_service._projection_guard.assert_mutable = (
            AsyncMock()
        )  # pylint: disable=protected-access
        revision_service._rsg.insert_one = AsyncMock(
            return_value={"id": ids["revision"]}
        )  # pylint: disable=protected-access
        await revision_service.create(
            {
                "tenant_id": ids["tenant"],
                "knowledge_pack_version_id": ids["version"],
            }
        )
        revision_service.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(
                tenant_id=ids["tenant"],
                knowledge_pack_version_id=ids["version"],
                status="draft",
            )
        )
        revision_service._rsg.update_one = (
            AsyncMock(  # pylint: disable=protected-access
                return_value={"id": ids["revision"]}
            )
        )
        await revision_service.update_with_row_version(
            {"id": ids["revision"]},
            expected_row_version=1,
            changes={"body": "changed"},
        )
        self.assertEqual(
            revision_service._projection_guard.assert_mutable.await_count,
            2,  # pylint: disable=protected-access
        )

    def test_runtime_registration_and_model_repr(self) -> None:
        gateway = _WritableGateway()
        configure_knowledge_gateway(gateway)
        self.assertIs(get_knowledge_gateway(), gateway)
        self.assertIn(
            "KnowledgeIndexProjection",
            KnowledgeIndexProjection.__repr__(SimpleNamespace(id=None)),
        )
        self.assertIn(
            "KnowledgeScope",
            KnowledgeScope.__repr__(SimpleNamespace(id=None)),
        )
        configure_knowledge_gateway(None)


class _RelationalFixture:
    def __init__(self, ids: dict[str, uuid.UUID]) -> None:
        self.ids = ids
        self.rows = {
            "knowledge_pack_knowledge_pack": {
                "id": ids["pack"],
                "current_version_id": ids["version"],
                "is_active": True,
            },
            "knowledge_pack_knowledge_pack_version": {
                "id": ids["version"],
                "status": "published",
            },
            "knowledge_pack_knowledge_entry": {
                "id": ids["entry"],
                "entry_key": "refund",
                "title": "Authoritative title",
                "is_active": True,
            },
            "knowledge_pack_knowledge_entry_revision": {
                "id": ids["revision"],
                "body": "Authoritative relational body",
                "body_json": None,
                "status": "published",
                "channel": "web",
                "category": "billing",
            },
            "knowledge_pack_knowledge_scope": {
                "id": ids["scope"],
                "channel": None,
                "locale": "en-US",
                "category": None,
                "service_route_key": "support",
                "client_profile_key": "retail",
                "service_profile_id": None,
                "is_active": True,
            },
            "knowledge_pack_knowledge_index_projection": {"id": uuid.uuid4()},
        }

    async def get_one(self, table, where, **kwargs):
        _ = kwargs
        row = self.rows.get(table)
        if row is None:
            return None
        for key, value in where.items():
            if key in row and row[key] != value:
                return None
        return dict(row)


class TestKnowledgeSafeRetrieval(unittest.IsolatedAsyncioTestCase):
    """Covers relational authority, readiness, and stale-hit rejection."""

    def _hit(self, ids, **changes) -> KnowledgeSearchHit:
        values = {
            **_document(ids).metadata(),
            "similarity": 0.8,
            "distance": 0.2,
            "snippet": "untrusted gateway body",
            **changes,
        }
        return KnowledgeSearchHit.from_mapping(values)

    async def test_search_returns_relational_content_and_deduplicates(self) -> None:
        ids = _ids()
        fixture = _RelationalFixture(ids)
        gateway = _WritableGateway(
            KnowledgeSearchResult(
                items=[self._hit(ids), self._hit(ids, similarity=0.9)]
            )
        )
        service = KnowledgeRetrievalService(
            rsg=fixture,  # type: ignore[arg-type]
            gateway=gateway,
        )
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            channel="web",
            locale="en-US",
            service_route_key="support",
        )
        results = await service.search(query)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].body, "Authoritative relational body")
        self.assertNotEqual(results[0].body, "untrusted gateway body")
        self.assertTrue(
            await service.current_projection_ready(
                tenant_id=ids["tenant"],
                knowledge_pack_version_id=ids["version"],
            )
        )

        gateway.result = KnowledgeSearchResult(
            items=[
                self._hit(ids, similarity=0.9),
                self._hit(ids, similarity=0.8),
            ]
        )
        self.assertEqual(len(await service.search(query)), 1)

        pack_scoped_query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            knowledge_pack_id=uuid.uuid4(),
        )
        self.assertEqual(await service.search(pack_scoped_query), [])

    async def test_service_profile_scope_is_relationally_revalidated(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        fixture = _RelationalFixture(ids)
        fixture.rows["knowledge_pack_knowledge_scope"][
            "service_profile_id"
        ] = service_profile_id
        fixture.rows["service_profile_service_profile"] = {
            "id": service_profile_id,
            "tenant_id": ids["tenant"],
            "status": "active",
            "deleted_at": None,
        }
        gateway = _WritableGateway(
            KnowledgeSearchResult(
                items=[
                    self._hit(
                        ids,
                        service_profile_id=str(service_profile_id),
                    )
                ]
            )
        )
        service = KnowledgeRetrievalService(
            rsg=fixture,  # type: ignore[arg-type]
            gateway=gateway,
        )
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            service_profile_id=service_profile_id,
        )
        results = await service.search(query)
        self.assertEqual(results[0].service_profile_id, service_profile_id)

        with patch.object(
            service,
            "_profile_active",
            new=AsyncMock(side_effect=[True, False]),
        ):
            self.assertEqual(await service.search(query), [])

        fixture.rows["service_profile_service_profile"]["status"] = "disabled"
        self.assertEqual(await service.search(query), [])

        fixture.rows["service_profile_service_profile"]["status"] = "active"
        unscoped_query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
        )
        self.assertEqual(await service.search(unscoped_query), [])
        self.assertFalse(
            service._scope_matches(  # pylint: disable=protected-access
                {"service_profile_id": service_profile_id},
                unscoped_query,
            )
        )
        self.assertFalse(
            service._scope_matches(  # pylint: disable=protected-access
                {"service_profile_id": service_profile_id},
                KnowledgeSearchQuery(
                    tenant_id=ids["tenant"],
                    query_text="refund",
                    service_profile_id=uuid.uuid4(),
                ),
            )
        )

    async def test_rejects_cross_tenant_stale_inactive_and_incomplete_hits(
        self,
    ) -> None:
        ids = _ids()
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"], query_text="refund", channel="web"
        )
        cases = []
        cases.append((self._hit(ids, tenant_id=str(uuid.uuid4())), None, None))
        incomplete = self._hit(ids)
        incomplete = KnowledgeSearchHit(
            tenant_id=incomplete.tenant_id,
            knowledge_pack_version_id=incomplete.knowledge_pack_version_id,
            knowledge_entry_revision_id=incomplete.knowledge_entry_revision_id,
        )
        cases.append((incomplete, None, None))
        cases.append(
            (
                self._hit(ids, channel="voice"),
                "knowledge_pack_knowledge_scope",
                ("channel", "voice"),
            )
        )
        for table, field, value in (
            ("knowledge_pack_knowledge_pack", "current_version_id", uuid.uuid4()),
            ("knowledge_pack_knowledge_pack_version", "status", "archived"),
            ("knowledge_pack_knowledge_entry", "entry_key", "changed"),
            ("knowledge_pack_knowledge_entry_revision", "status", "archived"),
            ("knowledge_pack_knowledge_scope", "channel", "voice"),
            ("knowledge_pack_knowledge_scope", "id", None),
            ("knowledge_pack_knowledge_index_projection", "id", None),
        ):
            cases.append((self._hit(ids), table, (field, value)))

        for hit, table, mutation in cases:
            fixture = _RelationalFixture(ids)
            if table is not None and mutation is not None:
                field, value = mutation
                if value is None:
                    fixture.rows[table] = None
                else:
                    fixture.rows[table][field] = value
            service = KnowledgeRetrievalService(
                rsg=fixture,  # type: ignore[arg-type]
                gateway=_WritableGateway(KnowledgeSearchResult(items=[hit])),
            )
            with self.subTest(table=table, mutation=mutation):
                self.assertEqual(await service.search(query), [])
