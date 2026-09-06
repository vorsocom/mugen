"""Wire-level tests for the Chroma knowledge gateway HTTP transport."""

from __future__ import annotations

import json
from typing import Any
import unittest
from unittest.mock import patch

import httpx

from mugen.core.gateway.knowledge.chroma_http import ChromaHttpClient

_COLLECTION_ID = "62cf5a9f-93bc-43f3-87bb-f581d612726a"
_DEFAULT_COLLECTIONS = (
    "/api/v2/tenants/default_tenant/databases/default_database/collections"
)


class TestChromaHttpClient(unittest.TestCase):
    """Exercise real HTTP serialization and response handling without a server."""

    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response_status = 200
        self.response_payload: Any = {"id": _COLLECTION_ID}
        self.response_content: bytes | None = None

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.response_content is not None:
            return httpx.Response(self.response_status, content=self.response_content)
        return httpx.Response(self.response_status, json=self.response_payload)

    def _client(self, **kwargs: Any) -> ChromaHttpClient:
        http_client = httpx.Client
        with patch(
            "mugen.core.gateway.knowledge.chroma_http.httpx.Client",
            side_effect=lambda **options: http_client(
                transport=httpx.MockTransport(self._handler), **options
            ),
        ):
            client = ChromaHttpClient(**kwargs)
        self.addCleanup(client.close)
        return client

    def test_default_scope_and_query_response(self) -> None:
        client = self._client(host="chroma.local")
        collection = client.get_collection("knowledge_docs")
        self.assertEqual(
            str(self.requests[0].url),
            f"http://chroma.local:8000{_DEFAULT_COLLECTIONS}/knowledge_docs",
        )
        self.assertEqual(self.requests[0].method, "GET")
        self.assertEqual(
            self.requests[0].extensions["timeout"],
            {"connect": None, "read": None, "write": None, "pool": None},
        )
        query_response = {
            "ids": [["doc-1"]],
            "metadatas": [[{"tenant_id": "tenant-a", "title": "Refunds"}]],
            "documents": [["Refund policy"]],
            "distances": [[0.1]],
        }
        self.response_payload = query_response
        result = collection.query(
            query_embeddings=[[0.1, 0.2]],
            n_results=5,
            where={"tenant_id": "tenant-a"},
            include=["metadatas", "documents", "distances"],
        )
        self.assertEqual(result, query_response)
        request = self.requests[-1]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.url.path,
            f"{_DEFAULT_COLLECTIONS}/{_COLLECTION_ID}/query",
        )
        self.assertEqual(request.headers["content-type"], "application/json")
        self.assertEqual(
            json.loads(request.content),
            {
                "query_embeddings": [[0.1, 0.2]],
                "n_results": 5,
                "where": {"tenant_id": "tenant-a"},
                "where_document": None,
                "include": ["metadatas", "documents", "distances"],
            },
        )

    def test_configured_scope_headers_timeout_and_encoded_components(self) -> None:
        client = self._client(
            host="https://chroma.local:9443/proxy/api/v2/",
            port=9999,
            headers={"Authorization": "Bearer test-token", "X-Custom": "value"},
            tenant="tenant/name",
            database="database ?#%",
            timeout=2.5,
        )
        client.get_collection("knowledge/name ?#%")
        request = self.requests[-1]
        self.assertEqual(
            str(request.url),
            "https://chroma.local:9443/proxy/api/v2/tenants/tenant%2Fname"
            "/databases/database%20%3F%23%25/collections/knowledge%2Fname%20%3F%23%25",
        )
        self.assertEqual(request.headers["authorization"], "Bearer test-token")
        self.assertEqual(request.headers["x-custom"], "value")
        self.assertEqual(
            request.extensions["timeout"],
            {"connect": 2.5, "read": 2.5, "write": 2.5, "pool": 2.5},
        )

    def test_host_forms_keep_the_configured_endpoint(self) -> None:
        cases = (
            (
                {"host": "chroma.local", "port": 9000, "ssl": True},
                "https://chroma.local:9000/api/v2",
            ),
            (
                {"host": "http://chroma.local/proxy/", "ssl": True},
                "https://chroma.local/proxy/api/v2",
            ),
            (
                {"host": "http://chroma.local", "port": 9000},
                "http://chroma.local/api/v2",
            ),
            (
                {"host": "http://chroma.local/proxy%20path"},
                "http://chroma.local/proxy%20path/api/v2",
            ),
            ({"host": "chroma.local:9000"}, "http://chroma.local:9000/api/v2"),
            ({"host": "::1", "port": 9000}, "http://[::1]:9000/api/v2"),
            ({"host": "[::1]", "port": 9000}, "http://[::1]:9000/api/v2"),
        )
        for options, base_url in cases:
            with self.subTest(options=options):
                client = self._client(**options)
                client.get_collection("knowledge_docs")
                self.assertEqual(
                    str(self.requests[-1].url),
                    base_url + "/tenants/default_tenant/databases/default_database"
                    "/collections/knowledge_docs",
                )

    def test_dot_segments_cannot_change_scope(self) -> None:
        client = self._client(host="chroma.local", tenant="..", database=".")
        client.get_collection("..")
        self.assertEqual(
            self.requests[-1].url.raw_path,
            b"/api/v2/tenants/%2E%2E/databases/%2E/collections/%2E%2E",
        )

    def test_invalid_hosts_fail_before_opening_an_http_client(self) -> None:
        hosts = (
            "",
            "chroma.local/proxy",
            "ftp://chroma.local",
            "http:///missing-host",
            "http://user:password@chroma.local",
            "http://chroma.local?query=value",
            "http://chroma.local#fragment",
            "http://chroma.local:invalid",
        )
        for host in hosts:
            with self.subTest(host=host), patch(
                "mugen.core.gateway.knowledge.chroma_http.httpx.Client"
            ) as http_client:
                with self.assertRaises(ValueError):
                    ChromaHttpClient(host=host)
                http_client.assert_not_called()

    def test_query_and_delete_preserve_all_metadata_constraints(self) -> None:
        client = self._client(host="chroma.local")
        collection = client.get_collection("knowledge_docs")
        self.response_payload = {"ids": [[]], "metadatas": [[]]}
        constraints = {"tenant_id": "tenant-a", "knowledge_pack_id": "pack-a"}
        expected_where = {
            "$and": [{"tenant_id": "tenant-a"}, {"knowledge_pack_id": "pack-a"}]
        }
        collection.query(
            query_embeddings=[[0.1, 0.2]],
            n_results=2,
            where=constraints,
            include=["metadatas"],
        )
        self.assertEqual(json.loads(self.requests[-1].content)["where"], expected_where)
        self.assertEqual(
            constraints, {"tenant_id": "tenant-a", "knowledge_pack_id": "pack-a"}
        )

        self.response_payload = None
        collection.delete(where=constraints, ids=["doc-1"])
        request = self.requests[-1]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.url.path, f"{_DEFAULT_COLLECTIONS}/{_COLLECTION_ID}/delete"
        )
        self.assertEqual(
            json.loads(request.content),
            {"ids": ["doc-1"], "where": expected_where, "where_document": None},
        )
        collection.delete(where={"tenant_id": "tenant-a"})
        self.assertEqual(
            json.loads(self.requests[-1].content),
            {"ids": None, "where": {"tenant_id": "tenant-a"}, "where_document": None},
        )

        self.response_payload = {"ids": [[]]}
        collection.query(
            query_embeddings=[[0.1, 0.2]],
            n_results=2,
            where=expected_where,
            include=["metadatas"],
        )
        self.assertEqual(json.loads(self.requests[-1].content)["where"], expected_where)

    def test_upsert_sends_explicit_embeddings_and_accepts_empty_success(self) -> None:
        client = self._client(host="chroma.local")
        collection = client.get_collection("knowledge_docs")
        self.response_status = 204
        self.response_content = b""
        collection.upsert(
            ids=["doc-1"],
            embeddings=[[0.1, 0.2]],
            documents=["Refund policy"],
            metadatas=[{"tenant_id": "tenant-a", "title": "Refunds"}],
        )
        request = self.requests[-1]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            request.url.path, f"{_DEFAULT_COLLECTIONS}/{_COLLECTION_ID}/upsert"
        )
        self.assertEqual(
            json.loads(request.content),
            {
                "ids": ["doc-1"],
                "embeddings": [[0.1, 0.2]],
                "documents": ["Refund policy"],
                "metadatas": [{"tenant_id": "tenant-a", "title": "Refunds"}],
                "uris": None,
            },
        )

    def test_collection_metadata_cannot_override_scope_or_embedding_behavior(
        self,
    ) -> None:
        client = self._client(
            host="chroma.local", tenant="tenant-a", database="database-a"
        )
        self.response_payload = {
            "id": _COLLECTION_ID.upper(),
            "tenant": "other-tenant",
            "database": "other-database",
            "configuration_json": {"embedding_function": {"type": "custom"}},
        }
        collection = client.get_collection("knowledge_docs")
        self.response_payload = None
        collection.delete(where={"tenant_id": "tenant-a"})
        self.assertEqual(
            self.requests[-1].url.path,
            f"/api/v2/tenants/tenant-a/databases/database-a/collections/{_COLLECTION_ID}/delete",
        )

    def test_http_errors_invalid_json_and_bad_collection_payloads(self) -> None:
        client = self._client(host="chroma.local")
        for status in (401, 404, 429, 503):
            with self.subTest(status=status):
                self.response_status = status
                self.response_payload = {"error": "not available"}
                with self.assertRaises(httpx.HTTPStatusError) as raised:
                    client.get_collection("knowledge_docs")
                self.assertEqual(raised.exception.response.status_code, status)

        self.response_status = 200
        self.response_content = b"invalid json"
        with self.assertRaises(ValueError):
            client.get_collection("knowledge_docs")
        self.response_content = None
        for payload in (None, [], {}, {"id": 123}, {"id": "../../escape"}):
            with self.subTest(payload=payload):
                self.response_payload = payload
                with self.assertRaises(ValueError):
                    client.get_collection("knowledge_docs")

    def test_invalid_query_payload_and_closed_transport(self) -> None:
        client = self._client(host="chroma.local")
        collection = client.get_collection("knowledge_docs")
        for payload in ([], {}, {"ids": None}, {"ids": "invalid"}):
            with self.subTest(payload=payload):
                self.response_payload = payload
                with self.assertRaisesRegex(ValueError, "invalid query payload"):
                    collection.query(
                        query_embeddings=[[0.1, 0.2]],
                        n_results=2,
                        where={"tenant_id": "tenant-a"},
                        include=["metadatas"],
                    )
        client.close()
        client.close()
        with self.assertRaises(RuntimeError):
            client.get_collection("knowledge_docs")


if __name__ == "__main__":
    unittest.main()
