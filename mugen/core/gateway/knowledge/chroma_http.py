"""Provide the Chroma HTTP operations used by the knowledge gateway.

This adapter replaces the SDK to remove bundled code affected by CVE-2026-45830,
CVE-2026-45831, and CVE-2026-45833 while preserving remote Chroma operations.
The official SDK can be restored once a release is verified to fix or exclude
the affected code. See docs/security/dependabot-chromadb-remediation.md for the
rationale and restoration checks, including tenant filters and local embeddings.
"""

__all__ = ["ChromaHttpClient"]

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

import httpx


def _path_component(value: str) -> str:
    """Encode one path component, including URL dot segments."""
    encoded = quote(value, safe="")
    if encoded in {".", ".."}:
        return encoded.replace(".", "%2E")
    return encoded


def _where_filter(where: dict[str, Any]) -> dict[str, Any]:
    """Express multiple metadata predicates using Chroma's conjunction syntax."""
    if len(where) > 1:
        return {"$and": [{key: value} for key, value in where.items()]}
    return dict(where)


class ChromaHttpClient:
    """Access an existing Chroma collection through its v2 HTTP API."""

    def __init__(
        self,
        host: str,
        port: int = 8000,
        ssl: bool = False,
        headers: dict[str, str] | None = None,
        tenant: str = "default_tenant",
        database: str = "default_database",
        timeout: float | None = None,
    ) -> None:
        self._base_url = self._resolve_url(host, port=port, ssl=ssl)
        self._collections_path = (
            f"/tenants/{_path_component(tenant)}"
            f"/databases/{_path_component(database)}/collections"
        )
        self._session = httpx.Client(headers=headers, timeout=timeout)

    @staticmethod
    def _resolve_url(host: str, *, port: int, ssl: bool) -> str:
        full_url = "://" in host
        if not full_url:
            if "/" in host:
                raise ValueError(
                    "Chroma host paths require an http:// or https:// URL."
                )
            if host.count(":") > 1 and not host.startswith("["):
                host = f"[{host}]"
        parsed = urlsplit(host if full_url else f"//{host}")
        if (
            (full_url and parsed.scheme not in {"http", "https"})
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Chroma host must be an HTTP endpoint without credentials, query, or fragment."
            )
        # Accessing port also validates ports embedded in a full URL.
        parsed_port = parsed.port
        scheme = "https" if ssl else parsed.scheme or "http"
        netloc = parsed.netloc
        if not full_url and parsed_port is None:
            netloc = f"{netloc}:{port}"
        path = parsed.path.rstrip("/")
        if not path.endswith("/api/v2"):
            path += "/api/v2"
        return urlunsplit((scheme, netloc, path, "", ""))

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._session.request(method, self._base_url + path, **kwargs)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def get_collection(self, name: str) -> "_ChromaHttpCollection":
        """Resolve a collection name to its UUID within the configured scope."""
        payload = self._request(
            "GET", f"{self._collections_path}/{_path_component(name)}"
        )
        if not isinstance(payload, dict):
            raise ValueError("Chroma returned an invalid collection payload.")
        collection_id = payload.get("id")
        if not isinstance(collection_id, str):
            raise ValueError("Chroma returned an invalid collection ID.")
        collection_id = str(uuid.UUID(collection_id))
        return _ChromaHttpCollection(self, f"{self._collections_path}/{collection_id}")

    def close(self) -> None:
        """Release HTTP connections."""
        self._session.close()


class _ChromaHttpCollection:
    """Send explicit embeddings and metadata to one resolved collection."""

    def __init__(self, client: ChromaHttpClient, path: str) -> None:
        self._client = client
        self._path = path

    def query(
        self,
        *,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, Any],
        include: list[str],
    ) -> dict[str, Any]:
        """Query existing vectors without constructing an embedding function."""
        payload = self._client._request(  # pylint: disable=protected-access
            "POST",
            f"{self._path}/query",
            json={
                "query_embeddings": query_embeddings,
                "n_results": n_results,
                "where": _where_filter(where),
                "where_document": None,
                "include": include,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("ids"), list):
            raise ValueError("Chroma returned an invalid query payload.")
        return payload

    def upsert(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert documents whose embeddings are supplied by the gateway."""
        self._client._request(  # pylint: disable=protected-access
            "POST",
            f"{self._path}/upsert",
            json={
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
                "uris": None,
            },
        )

    def delete(
        self,
        *,
        where: dict[str, Any],
        ids: list[str] | None = None,
    ) -> None:
        """Delete documents matching the gateway's mandatory metadata scope."""
        self._client._request(  # pylint: disable=protected-access
            "POST",
            f"{self._path}/delete",
            json={
                "ids": ids,
                "where": _where_filter(where),
                "where_document": None,
            },
        )
