"""Exercise the Chroma gateway against its real HTTP adapter and mocked server."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, call, patch
import uuid

import httpx

from mugen.core.contract.gateway.knowledge import (
    KnowledgeDeleteSelector,
    KnowledgeGatewayRuntimeError,
    KnowledgeIndexDocument,
    KnowledgeSearchQuery,
)
from mugen.core.gateway.knowledge.chromadb import ChromaKnowledgeGateway
from mugen.core.gateway.knowledge.common import DEFAULT_ENCODER_REVISION
from mugen_test.test_mugen_gateway_knowledge_chromadb import _make_config


class TestChromaGatewayHttpIntegration(unittest.IsolatedAsyncioTestCase):
    """Keep local embedding and tenant governance across the HTTP boundary."""

    def setUp(self) -> None:
        self.document = KnowledgeIndexDocument(
            document_id="refund-document",
            tenant_id=uuid.UUID(int=1),
            knowledge_pack_id=uuid.UUID(int=2),
            knowledge_pack_version_id=uuid.UUID(int=3),
            knowledge_entry_id=uuid.UUID(int=4),
            knowledge_entry_revision_id=uuid.UUID(int=5),
            knowledge_scope_id=uuid.UUID(int=6),
            entry_key="refund",
            title="Refund policy",
            content="Approved refund answer",
            content_checksum="a" * 64,
            projection_schema_version=1,
            search_content="Refund question and answer",
            channel="web",
        )
        self.collection_id = str(uuid.UUID(int=7))
        self.collection_path = (
            "/proxy/api/v2/tenants/service-tenant/databases/knowledge/collections"
        )

    def _gateway(self, responses: list[httpx.Response]):
        requests = []
        sessions = []
        http_client = httpx.Client

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return responses.pop(0)

        def build_client(**kwargs):
            session = http_client(transport=httpx.MockTransport(respond), **kwargs)
            sessions.append(session)
            self.addCleanup(session.close)
            return session

        self.enterContext(
            patch(
                "mugen.core.gateway.knowledge.chroma_http.httpx.Client",
                side_effect=build_client,
            )
        )
        encoder_type = self.enterContext(
            patch("mugen.core.gateway.knowledge.chromadb.SentenceTransformer")
        )
        encoder_type.return_value.encode.return_value = [0.25, 0.75]
        gateway = ChromaKnowledgeGateway(
            _make_config(
                host="https://chroma.example/proxy",
                headers={"Authorization": "Bearer configured-test-token"},
                tenant="service-tenant",
                database="knowledge",
            ),
            Mock(),
        )
        self.addAsyncCleanup(gateway.aclose)
        return gateway, encoder_type, requests, sessions

    async def test_governed_documents_use_local_embeddings_and_scoped_http(self):
        metadata = {**self.document.metadata(), "body": self.document.content}
        gateway, encoder_type, requests, sessions = self._gateway(
            [
                httpx.Response(
                    200,
                    json={
                        "id": self.collection_id,
                        "metadata": {"embedding_function": "untrusted.server.marker"},
                        "configuration_json": {
                            "embedding_function": {
                                "type": "known",
                                "name": "untrusted.server.marker",
                                "config": {"model_name": "untrusted/server-model"},
                            }
                        },
                    },
                ),
                httpx.Response(200),
                httpx.Response(
                    200,
                    json={
                        "ids": [[self.document.document_id]],
                        "metadatas": [[metadata]],
                        "documents": [[self.document.content]],
                        "distances": [[0.125]],
                    },
                ),
                httpx.Response(200),
            ]
        )

        await gateway.check_readiness()
        write_result = await gateway.upsert_documents([self.document])
        search_result = await gateway.search(
            KnowledgeSearchQuery(
                tenant_id=self.document.tenant_id,
                knowledge_pack_id=self.document.knowledge_pack_id,
                knowledge_pack_version_id=self.document.knowledge_pack_version_id,
                query_text="How do I get a refund?",
                channel="web",
            )
        )
        delete_result = await gateway.delete_documents(
            KnowledgeDeleteSelector(
                tenant_id=self.document.tenant_id,
                knowledge_pack_id=self.document.knowledge_pack_id,
                knowledge_pack_version_id=self.document.knowledge_pack_version_id,
                document_ids=(self.document.document_id,),
            )
        )
        await gateway.aclose()

        self.assertEqual(write_result.affected_count, 1)
        self.assertEqual(delete_result.affected_count, 1)
        self.assertEqual(len(search_result.items), 1)
        self.assertEqual(search_result.items[0].tenant_id, self.document.tenant_id)
        self.assertEqual(search_result.items[0].snippet, self.document.content)
        self.assertEqual(search_result.items[0].similarity, 0.875)
        self.assertEqual(
            [(request.method, request.url.path) for request in requests],
            [
                ("GET", f"{self.collection_path}/downstream_kp_search_doc"),
                ("POST", f"{self.collection_path}/{self.collection_id}/upsert"),
                ("POST", f"{self.collection_path}/{self.collection_id}/query"),
                ("POST", f"{self.collection_path}/{self.collection_id}/delete"),
            ],
        )
        for request in requests:
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.host, "chroma.example")
            self.assertEqual(
                request.headers["Authorization"], "Bearer configured-test-token"
            )
            self.assertEqual(
                request.extensions["timeout"],
                {key: 2.5 for key in ("connect", "read", "write", "pool")},
            )
        upsert = json.loads(requests[1].content)
        self.assertEqual(upsert["ids"], [self.document.document_id])
        self.assertEqual(upsert["embeddings"], [[0.25, 0.75]])
        self.assertEqual(upsert["documents"], [self.document.content])
        self.assertEqual(
            upsert["metadatas"][0]["tenant_id"], str(self.document.tenant_id)
        )
        self.assertEqual(upsert["metadatas"][0]["body"], self.document.content)
        scope = {
            "$and": [
                {"tenant_id": str(self.document.tenant_id)},
                {"knowledge_pack_id": str(self.document.knowledge_pack_id)},
                {
                    "knowledge_pack_version_id": str(
                        self.document.knowledge_pack_version_id
                    )
                },
            ]
        }
        query = json.loads(requests[2].content)
        self.assertEqual(query["query_embeddings"], [[0.25, 0.75]])
        self.assertEqual(query["where"], scope)
        self.assertEqual(query["n_results"], 50)
        self.assertEqual(query["include"], ["metadatas", "documents", "distances"])
        deletion = json.loads(requests[3].content)
        self.assertEqual(deletion["where"], scope)
        self.assertEqual(deletion["ids"], [self.document.document_id])
        encoder_type.assert_called_once()
        self.assertEqual(
            encoder_type.call_args.kwargs["model_name_or_path"], "all-mpnet-base-v2"
        )
        self.assertEqual(
            encoder_type.call_args.kwargs["revision"], DEFAULT_ENCODER_REVISION
        )
        self.assertFalse(encoder_type.call_args.kwargs["trust_remote_code"])
        self.assertEqual(
            encoder_type.return_value.encode.call_args_list,
            [call(self.document.search_content), call("How do I get a refund?")],
        )
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].is_closed)

    async def test_readiness_preserves_collection_http_failure(self):
        gateway, encoder_type, requests, _ = self._gateway(
            [httpx.Response(404, json={"error": "NotFoundError"})]
        )
        with self.assertRaisesRegex(RuntimeError, "readiness probe failed") as raised:
            await gateway.check_readiness()
        self.assertIsInstance(raised.exception.__cause__, httpx.HTTPStatusError)
        self.assertEqual(raised.exception.__cause__.response.status_code, 404)
        encoder_type.assert_not_called()
        self.assertEqual(len(requests), 1)

    async def test_search_wraps_http_failure_with_provider_and_operation(self):
        gateway, _, requests, _ = self._gateway(
            [
                httpx.Response(200, json={"id": self.collection_id}),
                httpx.Response(503, json={"error": "ServiceUnavailable"}),
            ]
        )
        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(
                KnowledgeSearchQuery(
                    tenant_id=self.document.tenant_id,
                    query_text="How do I get a refund?",
                )
            )
        self.assertEqual(raised.exception.provider, "chromadb")
        self.assertEqual(raised.exception.operation, "search")
        self.assertIsInstance(raised.exception.cause, httpx.HTTPStatusError)
        self.assertEqual(raised.exception.cause.response.status_code, 503)
        self.assertIs(raised.exception.__cause__, raised.exception.cause)
        self.assertEqual(
            json.loads(requests[1].content)["where"],
            {"tenant_id": str(self.document.tenant_id)},
        )
