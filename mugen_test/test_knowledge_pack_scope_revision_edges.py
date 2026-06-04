"""Unit tests for knowledge_pack scope and revision service edge branches."""

import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeEntryRevisionDE,
    KnowledgePackVersionDE,
    KnowledgeScopeDE,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_entry_revision import (
    KnowledgeEntryRevisionService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import (
    KnowledgeScopeService,
)


class TestKnowledgePackScopeRevisionEdges(unittest.IsolatedAsyncioTestCase):
    """Covers low-coverage helper/error branches in knowledge_pack services."""

    async def test_entry_revision_update_with_row_version_error_paths(self) -> None:
        svc = KnowledgeEntryRevisionService(
            table="knowledge_pack_knowledge_entry_revision",
            rsg=Mock(),
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.update_with_row_version(
                where,
                expected_row_version=1,
                changes={"body": "x"},
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(return_value=None)
        result = await svc.update_with_row_version(
            where,
            expected_row_version=1,
            changes={"body": "x"},
        )
        self.assertIsNone(result)

        svc.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(
                id=where["id"],
                tenant_id=where["tenant_id"],
                status="draft",
                row_version=1,
            )
        )
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=RowVersionConflict("knowledge_pack_revision")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await svc.update_with_row_version(
                    where,
                    expected_row_version=1,
                    changes={"body": "x"},
                )
        self.assertEqual(ctx.exception.code, 409)

        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=SQLAlchemyError("boom")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await svc.update_with_row_version(
                    where,
                    expected_row_version=1,
                    changes={"body": "x"},
                )
        self.assertEqual(ctx.exception.code, 500)

    async def test_entry_revision_update_with_row_version_success_path(self) -> None:
        svc = KnowledgeEntryRevisionService(
            table="knowledge_pack_knowledge_entry_revision",
            rsg=Mock(),
        )
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        updated = KnowledgeEntryRevisionDE(
            id=where["id"],
            tenant_id=where["tenant_id"],
            status="review",
            row_version=2,
        )
        svc.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(
                id=where["id"],
                tenant_id=where["tenant_id"],
                status="draft",
                row_version=1,
            )
        )

        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=updated),
        ):
            result = await svc.update_with_row_version(
                where,
                expected_row_version=1,
                changes={"status": "review"},
            )

        self.assertEqual(result, updated)

    async def test_scope_list_published_revisions_handles_scope_query_errors(
        self,
    ) -> None:
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.list_published_revisions(tenant_id=uuid.uuid4())
        self.assertEqual(ctx.exception.code, 500)

    async def test_scope_list_published_revisions_returns_empty_when_no_scopes(
        self,
    ) -> None:
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(return_value=[])

        result = await svc.list_published_revisions(tenant_id=uuid.uuid4())

        self.assertEqual(result, [])

    async def test_scope_list_published_revisions_handles_missing_ids_and_no_candidates(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=None,
                    is_active=True,
                ),
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=None,
                    knowledge_entry_revision_id=uuid.uuid4(),
                    is_active=True,
                ),
            ]
        )

        result = await svc.list_published_revisions(
            tenant_id=tenant_id,
            channel="chat",
            locale="en-US",
            category="billing",
        )
        self.assertEqual(result, [])

    async def test_scope_list_published_revisions_raises_500_on_lookup_errors(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=uuid.uuid4(),
                    is_active=True,
                )
            ]
        )
        svc._version_service.get = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.list_published_revisions(tenant_id=tenant_id)
        self.assertEqual(ctx.exception.code, 500)

    async def test_scope_list_published_revisions_filters_missing_and_unpublished(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=revision_id,
                    is_active=True,
                ),
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=uuid.uuid4(),
                    is_active=True,
                ),
            ]
        )
        svc._version_service.get = AsyncMock(
            side_effect=[
                KnowledgePackVersionDE(status="published"),
                None,
            ]
        )
        svc._revision_service.get = AsyncMock(
            side_effect=[
                KnowledgeEntryRevisionDE(id=revision_id, status="review"),
                None,
            ]
        )

        result = await svc.list_published_revisions(tenant_id=tenant_id)
        self.assertEqual(result, [])

    async def test_scope_list_published_revisions_raises_500_on_final_list_error(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=revision_id,
                    is_active=True,
                )
            ]
        )
        svc._version_service.get = AsyncMock(
            return_value=KnowledgePackVersionDE(status="published")
        )
        svc._revision_service.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(id=revision_id, status="published")
        )
        svc._revision_service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with self.assertRaises(HTTPException) as ctx:
            await svc.list_published_revisions(tenant_id=tenant_id)
        self.assertEqual(ctx.exception.code, 500)

    async def test_scope_list_published_revisions_success_filters_final_results(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        svc.list = AsyncMock(
            return_value=[
                KnowledgeScopeDE(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=uuid.uuid4(),
                    knowledge_entry_revision_id=revision_id,
                    is_active=True,
                )
            ]
        )
        svc._version_service.get = AsyncMock(
            return_value=KnowledgePackVersionDE(status="published")
        )
        svc._revision_service.get = AsyncMock(
            return_value=KnowledgeEntryRevisionDE(id=revision_id, status="published")
        )
        svc._revision_service.list = AsyncMock(
            return_value=[
                KnowledgeEntryRevisionDE(id=revision_id, status="published"),
                KnowledgeEntryRevisionDE(id=uuid.uuid4(), status="draft"),
            ]
        )

        result = await svc.list_published_revisions(tenant_id=tenant_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, revision_id)

    async def test_scope_list_published_revisions_filters_route_profile_fallbacks(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        generic_revision_id = uuid.uuid4()
        route_revision_id = uuid.uuid4()
        unrelated_revision_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        scopes = [
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=generic_revision_id,
                channel="matrix",
                service_route_key=None,
                client_profile_key=None,
                is_active=True,
            ),
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=route_revision_id,
                channel="matrix",
                service_route_key=None,
                client_profile_key=None,
                is_active=True,
            ),
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=route_revision_id,
                channel="matrix",
                service_route_key="support.primary",
                client_profile_key="default",
                is_active=True,
            ),
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=unrelated_revision_id,
                channel="matrix",
                service_route_key="billing",
                client_profile_key="default",
                is_active=True,
            ),
        ]

        async def list_scopes(*, filter_groups, limit):
            _ = limit
            return [
                scope
                for scope in scopes
                if any(
                    all(
                        getattr(scope, field) == expected
                        for field, expected in group.where.items()
                    )
                    for group in filter_groups
                )
            ]

        revisions = {
            generic_revision_id: KnowledgeEntryRevisionDE(
                id=generic_revision_id,
                status="published",
            ),
            route_revision_id: KnowledgeEntryRevisionDE(
                id=route_revision_id,
                status="published",
            ),
            unrelated_revision_id: KnowledgeEntryRevisionDE(
                id=unrelated_revision_id,
                status="published",
            ),
        }

        async def get_revision(where):
            return revisions[where["id"]]

        svc.list = AsyncMock(side_effect=list_scopes)
        svc._version_service.get = AsyncMock(
            return_value=KnowledgePackVersionDE(status="published")
        )
        svc._revision_service.get = AsyncMock(side_effect=get_revision)
        svc._revision_service.list = AsyncMock(
            return_value=[
                revisions[generic_revision_id],
                revisions[route_revision_id],
            ]
        )

        result = await svc.list_published_revisions(
            tenant_id=tenant_id,
            channel="matrix",
            service_route_key="support.primary",
            client_profile_key="default",
        )

        self.assertEqual(
            [revision.id for revision in result],
            [route_revision_id, generic_revision_id],
        )
        filter_groups = svc.list.await_args.kwargs["filter_groups"]
        self.assertEqual(len(filter_groups), 4)
        self.assertEqual(svc._revision_service.list.await_args.kwargs["limit"], 2)

    async def test_scope_list_published_revisions_without_route_uses_generic_scopes(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        generic_revision_id = uuid.uuid4()
        route_revision_id = uuid.uuid4()
        svc = KnowledgeScopeService(table="knowledge_pack_knowledge_scope", rsg=Mock())
        scopes = [
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=generic_revision_id,
                channel="matrix",
                service_route_key=None,
                client_profile_key=None,
                is_active=True,
            ),
            KnowledgeScopeDE(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
                knowledge_entry_revision_id=route_revision_id,
                channel="matrix",
                service_route_key="support.primary",
                client_profile_key="default",
                is_active=True,
            ),
        ]

        async def list_scopes(*, filter_groups, limit):
            _ = limit
            return [
                scope
                for scope in scopes
                if any(
                    all(
                        getattr(scope, field) == expected
                        for field, expected in group.where.items()
                    )
                    for group in filter_groups
                )
            ]

        revisions = {
            generic_revision_id: KnowledgeEntryRevisionDE(
                id=generic_revision_id,
                status="published",
            ),
            route_revision_id: KnowledgeEntryRevisionDE(
                id=route_revision_id,
                status="published",
            ),
        }

        async def get_revision(where):
            return revisions[where["id"]]

        svc.list = AsyncMock(side_effect=list_scopes)
        svc._version_service.get = AsyncMock(
            return_value=KnowledgePackVersionDE(status="published")
        )
        svc._revision_service.get = AsyncMock(side_effect=get_revision)
        svc._revision_service.list = AsyncMock(
            return_value=[
                revisions[generic_revision_id],
            ]
        )

        result = await svc.list_published_revisions(
            tenant_id=tenant_id,
            channel="matrix",
        )

        self.assertEqual([revision.id for revision in result], [generic_revision_id])
        filter_groups = svc.list.await_args.kwargs["filter_groups"]
        self.assertEqual(len(filter_groups), 1)
        self.assertEqual(filter_groups[0].where["service_route_key"], None)
        self.assertEqual(filter_groups[0].where["client_profile_key"], None)
