"""Projection write/delete and neutral search contract tests for all adapters."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.contract.gateway.knowledge import (
    KnowledgeDeleteSelector,
    KnowledgeGatewayRuntimeError,
    KnowledgeIndexDocument,
    KnowledgeSearchQuery,
)
from mugen_test import test_mugen_gateway_knowledge_chromadb as chroma_test
from mugen_test import test_mugen_gateway_knowledge_milvus as milvus_test
from mugen_test import test_mugen_gateway_knowledge_pgvector as pgvector_test
from mugen_test import test_mugen_gateway_knowledge_pinecone as pinecone_test
from mugen_test import test_mugen_gateway_knowledge_qdrant as qdrant_test
from mugen_test import test_mugen_gateway_knowledge_weaviate as weaviate_test


def _ids() -> dict[str, uuid.UUID]:
    return {
        name: uuid.uuid4()
        for name in ("tenant", "pack", "version", "entry", "revision", "scope")
    }


def _document(ids=None, **changes) -> KnowledgeIndexDocument:
    values = ids or _ids()
    kwargs = {
        "document_id": str(uuid.uuid4()),
        "tenant_id": values["tenant"],
        "knowledge_pack_id": values["pack"],
        "knowledge_pack_version_id": values["version"],
        "knowledge_entry_id": values["entry"],
        "knowledge_entry_revision_id": values["revision"],
        "knowledge_scope_id": values["scope"],
        "entry_key": "refund",
        "title": "Refund policy",
        "content": "Approved refund content",
        "content_checksum": "a" * 64,
        "projection_schema_version": 1,
        "search_content": "Refund question and approved answer",
        "channel": "web",
        "locale": "en-US",
        "category": "billing",
        "service_route_key": "support",
        "client_profile_key": None,
    }
    kwargs.update(changes)
    return KnowledgeIndexDocument(**kwargs)


def _selector(ids, *, document_ids=()):
    return KnowledgeDeleteSelector(
        tenant_id=ids["tenant"],
        knowledge_pack_id=ids["pack"],
        knowledge_pack_version_id=ids["version"],
        document_ids=document_ids,
    )


class _Result:
    def __init__(self, rowcount=1) -> None:
        self.rowcount = rowcount


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self.error = error

    async def execute(self, statement, params):
        self.calls.append((statement, params))
        if self.error is not None:
            raise self.error
        return _Result()


class _BeginContext:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Engine:
    def __init__(self, connection) -> None:
        self.connection = connection

    def begin(self):
        return _BeginContext(self.connection)


class TestKnowledgeGatewayProjectionAdapters(unittest.IsolatedAsyncioTestCase):
    """Exercises each provider's idempotent write/delete request construction."""

    def test_all_adapter_target_fingerprints_track_nonsecret_configuration(
        self,
    ) -> None:
        pairs = []
        pairs.append(
            (
                chroma_test._build_gateway(  # pylint: disable=protected-access
                    config=chroma_test._make_config(
                        collection="one"
                    )  # pylint: disable=protected-access
                )[0],
                chroma_test._build_gateway(  # pylint: disable=protected-access
                    config=chroma_test._make_config(
                        collection="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        pairs.append(
            (
                milvus_test._build_gateway(  # pylint: disable=protected-access
                    config=milvus_test._make_config(
                        vector_field="one"
                    )  # pylint: disable=protected-access
                )[0],
                milvus_test._build_gateway(  # pylint: disable=protected-access
                    config=milvus_test._make_config(
                        vector_field="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        pairs.append(
            (
                pgvector_test._build_gateway(  # pylint: disable=protected-access
                    config=pgvector_test._make_config(
                        search_table="one"
                    )  # pylint: disable=protected-access
                )[0],
                pgvector_test._build_gateway(  # pylint: disable=protected-access
                    config=pgvector_test._make_config(
                        search_table="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        pairs.append(
            (
                pinecone_test._build_gateway(  # pylint: disable=protected-access
                    config=pinecone_test._make_config(
                        namespace="one"
                    )  # pylint: disable=protected-access
                )[0],
                pinecone_test._build_gateway(  # pylint: disable=protected-access
                    config=pinecone_test._make_config(
                        namespace="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        pairs.append(
            (
                qdrant_test._build_gateway(  # pylint: disable=protected-access
                    config=qdrant_test._make_config(
                        search_collection="one"
                    )  # pylint: disable=protected-access
                )[0],
                qdrant_test._build_gateway(  # pylint: disable=protected-access
                    config=qdrant_test._make_config(
                        search_collection="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        pairs.append(
            (
                weaviate_test._build_gateway(  # pylint: disable=protected-access
                    config=weaviate_test._make_config(
                        target_vector="one"
                    )  # pylint: disable=protected-access
                )[0],
                weaviate_test._build_gateway(  # pylint: disable=protected-access
                    config=weaviate_test._make_config(
                        target_vector="two"
                    )  # pylint: disable=protected-access
                )[0],
            )
        )
        for first, second in pairs:
            with self.subTest(provider=first.provider_name):
                self.assertNotEqual(
                    first.configuration_fingerprint(),
                    second.configuration_fingerprint(),
                )

        first, _ = milvus_test._build_gateway(  # pylint: disable=protected-access
            config=milvus_test._make_config(
                token="secret-one"
            )  # pylint: disable=protected-access
        )
        second, _ = milvus_test._build_gateway(  # pylint: disable=protected-access
            config=milvus_test._make_config(
                token="secret-two"
            )  # pylint: disable=protected-access
        )
        self.assertEqual(
            first.configuration_fingerprint(),
            second.configuration_fingerprint(),
        )

    async def test_chroma_upsert_delete_empty_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        document = _document(
            ids,
            client_profile_key=None,
            service_profile_id=service_profile_id,
        )
        gateway, _ = chroma_test._build_gateway(  # pylint: disable=protected-access
            config=chroma_test._make_config()  # pylint: disable=protected-access
        )
        collection = SimpleNamespace(upsert=Mock(), delete=Mock())
        gateway._collection = collection  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).affected_count, 0)
        result = await gateway.upsert_documents([document])
        # pylint: disable=protected-access
        gateway._encode_search_term.assert_awaited_once_with(
            document.search_content
        )
        self.assertEqual(result.affected_count, 1)
        upsert_kwargs = collection.upsert.call_args.kwargs
        metadata = upsert_kwargs["metadatas"][0]
        self.assertEqual(upsert_kwargs["documents"], [document.content])
        self.assertEqual(metadata["body"], document.content)
        self.assertNotIn("search_content", metadata)
        self.assertEqual(metadata["client_profile_key"], "")
        self.assertEqual(metadata["document_id"], document.document_id)
        self.assertEqual(metadata["service_profile_id"], str(service_profile_id))
        await gateway.delete_documents(
            _selector(ids, document_ids=(document.document_id,))
        )
        self.assertIn("where", collection.delete.call_args.kwargs)
        self.assertIn("ids", collection.delete.call_args.kwargs)
        await gateway.delete_documents(_selector(ids))

        collection.query = Mock(return_value={})
        await gateway._query_collection(  # pylint: disable=protected-access
            query_vector=[0.1],
            tenant_id=str(ids["tenant"]),
            channel=None,
            locale=None,
            category=None,
            top_k=2,
            knowledge_pack_id=str(ids["pack"]),
            knowledge_pack_version_id=str(ids["version"]),
        )
        where = collection.query.call_args.kwargs["where"]
        self.assertEqual(where["knowledge_pack_id"], str(ids["pack"]))
        self.assertEqual(where["knowledge_pack_version_id"], str(ids["version"]))

        collection.upsert.side_effect = RuntimeError("write")
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents([document])
        collection.delete.side_effect = RuntimeError("delete")
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

    async def test_milvus_upsert_delete_empty_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        document = _document(ids, service_profile_id=service_profile_id)
        gateway, _ = milvus_test._build_gateway(  # pylint: disable=protected-access
            config=milvus_test._make_config()  # pylint: disable=protected-access
        )
        client = SimpleNamespace(upsert=Mock(), delete=Mock())
        gateway._client = client  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).requested_count, 0)
        await gateway.upsert_documents([document])
        # pylint: disable=protected-access
        gateway._encode_search_term.assert_awaited_once_with(
            document.search_content
        )
        row = client.upsert.call_args.kwargs["data"][0]
        self.assertEqual(row["id"], document.document_id)
        self.assertEqual(row["body"], document.content)
        self.assertNotIn("search_content", row)
        self.assertEqual(row["service_profile_id"], str(service_profile_id))
        await gateway.delete_documents(
            _selector(ids, document_ids=(document.document_id,))
        )
        self.assertIn("tenant_id", client.delete.call_args.kwargs["filter"])
        client.upsert = None
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents([document])
        client.upsert = Mock()
        client.delete = None
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

    async def test_pgvector_upsert_delete_empty_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        document = _document(ids, service_profile_id=service_profile_id)
        connection = _Connection()
        runtime = SimpleNamespace(
            engine=_Engine(connection),
            aclose=AsyncMock(),
        )
        gateway, _, _ = (
            pgvector_test._build_gateway(  # pylint: disable=protected-access
                config=pgvector_test._make_config(),  # pylint: disable=protected-access
                fake_runtime=runtime,
            )
        )
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).affected_count, 0)
        await gateway.upsert_documents([document])
        # pylint: disable=protected-access
        gateway._encode_search_term.assert_awaited_once_with(
            document.search_content
        )
        stored = connection.calls[0][1]
        self.assertEqual(stored["document_id"], document.document_id)
        self.assertEqual(stored["body"], document.content)
        self.assertNotIn("search_content", stored)
        self.assertEqual(
            stored["service_profile_id"],
            str(service_profile_id),
        )
        deleted = await gateway.delete_documents(
            _selector(ids, document_ids=(document.document_id,))
        )
        self.assertEqual(deleted.affected_count, 1)
        statement, params = (
            gateway._build_search_query(  # pylint: disable=protected-access
                query_vector="[0.1]",
                tenant_id=str(ids["tenant"]),
                channel=None,
                locale=None,
                category=None,
                top_k=2,
                min_similarity=None,
                knowledge_pack_id=str(ids["pack"]),
                knowledge_pack_version_id=str(ids["version"]),
            )
        )
        self.assertIn("knowledge_pack_id", statement)
        self.assertEqual(params["knowledge_pack_version_id"], str(ids["version"]))
        await gateway.delete_documents(
            KnowledgeDeleteSelector(
                tenant_id=ids["tenant"],
                knowledge_pack_version_id=ids["version"],
            )
        )
        await gateway.delete_documents(
            KnowledgeDeleteSelector(
                tenant_id=ids["tenant"],
                document_ids=(document.document_id,),
            )
        )

        runtime.engine = _Engine(_Connection(RuntimeError("db")))
        gateway._engine = runtime.engine  # pylint: disable=protected-access
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents([document])
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

    async def test_pinecone_upsert_delete_empty_namespace_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        documents = [
            _document(ids, service_profile_id=service_profile_id),
            _document(ids, channel=None),
        ]
        gateway, _ = pinecone_test._build_gateway(  # pylint: disable=protected-access
            config=pinecone_test._make_config(
                namespace="tenant"
            )  # pylint: disable=protected-access
        )
        index = SimpleNamespace(upsert=AsyncMock(), delete=AsyncMock())
        gateway._index = index  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).requested_count, 0)
        await gateway.upsert_documents(documents)
        self.assertEqual(
            # pylint: disable=protected-access
            gateway._encode_search_term.await_args_list[0].args[0],
            documents[0].search_content,
        )
        self.assertEqual(index.upsert.await_args.kwargs["namespace"], "tenant")
        first_metadata = index.upsert.await_args.kwargs["vectors"][0]["metadata"]
        self.assertEqual(first_metadata["body"], documents[0].content)
        self.assertNotIn("search_content", first_metadata)
        self.assertEqual(
            first_metadata["service_profile_id"],
            str(service_profile_id),
        )
        self.assertEqual(
            index.upsert.await_args.kwargs["vectors"][1]["metadata"]["channel"],
            "",
        )
        await gateway.delete_documents(
            _selector(ids, document_ids=(documents[0].document_id,))
        )
        self.assertIn("document_id", index.delete.await_args.kwargs["filter"])
        gateway._index = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents(documents)
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

        no_namespace, _ = (
            pinecone_test._build_gateway(  # pylint: disable=protected-access
                config=pinecone_test._make_config(
                    namespace=""
                )  # pylint: disable=protected-access
            )
        )
        no_namespace._index = SimpleNamespace(  # pylint: disable=protected-access
            upsert=AsyncMock(), delete=AsyncMock()
        )
        no_namespace._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        await no_namespace.upsert_documents([documents[0]])
        await no_namespace.delete_documents(_selector(ids))
        no_namespace_index = no_namespace._index  # pylint: disable=protected-access
        self.assertNotIn(
            "namespace",
            no_namespace_index.upsert.await_args.kwargs,
        )
        self.assertNotIn(
            "namespace",
            no_namespace_index.delete.await_args.kwargs,
        )

    async def test_qdrant_upsert_delete_empty_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        document = _document(ids, service_profile_id=service_profile_id)
        gateway, client, *_ = (
            qdrant_test._build_gateway(  # pylint: disable=protected-access
                config=qdrant_test._make_config(
                    max_retries=0
                )  # pylint: disable=protected-access
            )
        )
        client.upsert = AsyncMock()
        client.delete = AsyncMock()
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).requested_count, 0)
        await gateway.upsert_documents([document])
        # pylint: disable=protected-access
        gateway._encode_search_term.assert_awaited_once_with(
            document.search_content
        )
        point = client.upsert.await_args.kwargs["points"][0]
        self.assertEqual(str(point.id), document.document_id)
        self.assertEqual(point.payload["body"], document.content)
        self.assertNotIn("search_content", point.payload)
        self.assertEqual(point.payload["service_profile_id"], str(service_profile_id))
        await gateway.delete_documents(
            _selector(ids, document_ids=(document.document_id,))
        )
        self.assertIsNotNone(client.delete.await_args.kwargs["points_selector"])
        client.upsert = None
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents([document])
        client.upsert = AsyncMock()
        client.delete = None
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

    async def test_weaviate_upsert_replace_delete_empty_and_errors(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        documents = [
            _document(ids, service_profile_id=service_profile_id),
            _document(ids, channel=None),
        ]
        gateway, _ = weaviate_test._build_gateway(  # pylint: disable=protected-access
            config=weaviate_test._make_config()  # pylint: disable=protected-access
        )
        data = SimpleNamespace(
            exists=Mock(side_effect=[False, True]),
            insert=Mock(),
            replace=Mock(),
            delete_many=Mock(),
        )
        gateway._collection = SimpleNamespace(
            data=data
        )  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        self.assertEqual((await gateway.upsert_documents([])).requested_count, 0)
        await gateway.upsert_documents(documents)
        self.assertEqual(
            # pylint: disable=protected-access
            gateway._encode_search_term.await_args_list[0].args[0],
            documents[0].search_content,
        )
        data.insert.assert_called_once()
        data.replace.assert_called_once()
        insert_properties = data.insert.call_args.kwargs["properties"]
        self.assertEqual(insert_properties["body"], documents[0].content)
        self.assertNotIn("search_content", insert_properties)
        self.assertEqual(data.replace.call_args.kwargs["properties"]["channel"], "")
        self.assertEqual(
            data.insert.call_args.kwargs["properties"]["service_profile_id"],
            str(service_profile_id),
        )
        await gateway.delete_documents(_selector(ids))
        data.delete_many.assert_called_once()
        await gateway.delete_documents(
            _selector(ids, document_ids=(documents[0].document_id,))
        )
        filters = gateway._build_query_filters(  # pylint: disable=protected-access
            tenant_id=str(ids["tenant"]),
            channel=None,
            locale=None,
            category=None,
            knowledge_pack_id=str(ids["pack"]),
            knowledge_pack_version_id=str(ids["version"]),
        )
        self.assertIsNotNone(filters)
        gateway._collection = SimpleNamespace(
            data=SimpleNamespace()
        )  # pylint: disable=protected-access
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.upsert_documents(documents)
        with self.assertRaises(KnowledgeGatewayRuntimeError):
            await gateway.delete_documents(_selector(ids))

    async def test_all_adapters_apply_neutral_scope_precedence(self) -> None:
        ids = _ids()
        service_profile_id = uuid.uuid4()
        query = KnowledgeSearchQuery(
            tenant_id=ids["tenant"],
            query_text="refund",
            knowledge_pack_id=ids["pack"],
            knowledge_pack_version_id=ids["version"],
            channel="web",
            service_route_key="support",
            service_profile_id=service_profile_id,
            candidate_limit=2,
        )
        wildcard = _document(ids, channel=None, service_route_key=None).metadata()
        wildcard["similarity"] = 0.99
        exact = _document(ids, service_profile_id=service_profile_id).metadata()
        exact["similarity"] = 0.8
        adapters = []

        chroma, _ = chroma_test._build_gateway(  # pylint: disable=protected-access
            config=chroma_test._make_config()  # pylint: disable=protected-access
        )
        chroma._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        chroma._execute_with_retry = AsyncMock(
            return_value={}
        )  # pylint: disable=protected-access
        chroma._normalise_items = Mock(
            return_value=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(chroma)

        milvus, _ = milvus_test._build_gateway(  # pylint: disable=protected-access
            config=milvus_test._make_config()  # pylint: disable=protected-access
        )
        milvus._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        milvus._execute_with_retry = AsyncMock(
            return_value=[]
        )  # pylint: disable=protected-access
        milvus._normalise_items = Mock(
            return_value=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(milvus)

        pgvector, _, _ = (
            pgvector_test._build_gateway(  # pylint: disable=protected-access
                config=pgvector_test._make_config()  # pylint: disable=protected-access
            )
        )
        pgvector._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        pgvector._execute_with_retry = AsyncMock(
            return_value=[{}, {}]
        )  # pylint: disable=protected-access
        pgvector._normalise_item = Mock(
            side_effect=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(pgvector)

        pinecone, _ = pinecone_test._build_gateway(  # pylint: disable=protected-access
            config=pinecone_test._make_config()  # pylint: disable=protected-access
        )
        pinecone._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        pinecone._execute_with_retry = AsyncMock(
            return_value={}
        )  # pylint: disable=protected-access
        pinecone._normalise_items = Mock(
            return_value=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(pinecone)

        qdrant, *_ = qdrant_test._build_gateway(  # pylint: disable=protected-access
            config=qdrant_test._make_config()  # pylint: disable=protected-access
        )
        qdrant._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        qdrant._execute_with_retry = AsyncMock(
            return_value=[]
        )  # pylint: disable=protected-access
        qdrant._normalise_items = Mock(
            return_value=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(qdrant)

        weaviate, _ = weaviate_test._build_gateway(  # pylint: disable=protected-access
            config=weaviate_test._make_config()  # pylint: disable=protected-access
        )
        weaviate._encode_search_term = AsyncMock(
            return_value=[0.1]
        )  # pylint: disable=protected-access
        weaviate._build_query_filters = Mock(
            return_value="filter"
        )  # pylint: disable=protected-access
        weaviate._execute_with_retry = AsyncMock(
            return_value=[]
        )  # pylint: disable=protected-access
        weaviate._normalise_items = Mock(
            return_value=[wildcard, exact]
        )  # pylint: disable=protected-access
        adapters.append(weaviate)

        for adapter in adapters:
            with self.subTest(adapter=adapter.provider_name):
                result = await adapter.search(query)
                self.assertEqual(result.items[0].channel, "web")
                self.assertEqual(result.items[1].channel, None)
