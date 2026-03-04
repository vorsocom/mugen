"""Unit tests for mugen.core.gateway.knowledge.qdrant.QdrantKnowledgeGateway."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.qdrant.search import QdrantSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.qdrant import QdrantKnowledgeGateway


def _make_config(
    *,
    environment: str = "development",
    timeout_seconds: object = 2.5,
    max_retries: object = 1,
    retry_backoff_seconds: object = 0.0,
    search_collection: object = "downstream_kp_search_doc",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(environment=environment),
        qdrant=SimpleNamespace(
            api=SimpleNamespace(
                key="qdrant-key",
                url="https://qdrant.local",
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            search=SimpleNamespace(
                collection=search_collection,
                default_top_k=default_top_k,
                max_top_k=max_top_k,
                snippet_max_chars=snippet_max_chars,
            ),
            encoder=SimpleNamespace(
                model=encoder_model,
                max_concurrency=encoder_max_concurrency,
            ),
        ),
        transformers=SimpleNamespace(hf=SimpleNamespace(home="/tmp/hf")),
    )


def _payload(
    *,
    tenant_id: str | None = None,
    revision_id: str | None = None,
    version_id: str | None = None,
    channel: str | None = "web",
    locale: str | None = "en-US",
    category: str | None = "billing",
    title: str | None = "Title",
    body: str | None = "Body text",
) -> dict:
    return {
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "knowledge_entry_revision_id": revision_id or str(uuid.uuid4()),
        "knowledge_pack_version_id": version_id or str(uuid.uuid4()),
        "channel": channel,
        "locale": locale,
        "category": category,
        "title": title,
        "body": body,
    }


def _build_gateway(
    *,
    config: SimpleNamespace,
    logging_gateway: Mock | None = None,
    fake_client: SimpleNamespace | None = None,
):
    logger = logging_gateway or Mock()
    client = fake_client or SimpleNamespace(
        search=AsyncMock(return_value=[]),
        get_collections=AsyncMock(
            return_value=SimpleNamespace(
                collections=[SimpleNamespace(name="downstream_kp_search_doc")]
            )
        ),
    )
    with (
        patch(
            "mugen.core.gateway.knowledge.qdrant.AsyncQdrantClient",
            return_value=client,
        ),
        patch("mugen.core.gateway.knowledge.qdrant.SentenceTransformer") as sentence_transformer,
    ):
        gateway = QdrantKnowledgeGateway(config, logger)
    return gateway, client, logger, sentence_transformer


class _VectorLike:
    def tolist(self) -> list[float]:
        return [1.0, 2.0]


class _PointObject:
    def __init__(self, *, payload: dict, score: object) -> None:
        self.payload = payload
        self.score = score


class _PointWithModelDump:
    def __init__(self, *, payload: dict, score: object) -> None:
        self._payload = payload
        self._score = score

    def model_dump(self):
        return {
            "payload": dict(self._payload),
            "score": self._score,
        }


class TestMugenGatewayKnowledgeQdrant(unittest.IsolatedAsyncioTestCase):
    """Coverage for Qdrant knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        gateway, _client, _logger, _ = _build_gateway(
            config=_make_config(
                timeout_seconds=None,
                default_top_k=None,
                max_top_k=None,
                snippet_max_chars=None,
                encoder_model=123,
                encoder_max_concurrency=0,
            )
        )
        self.assertIsNone(gateway._api_timeout_seconds)  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            gateway._search_collection,
            "downstream_kp_search_doc",
        )
        self.assertEqual(gateway._search_default_top_k, 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_max_top_k, 50)  # pylint: disable=protected-access
        self.assertEqual(gateway._snippet_max_chars, 240)  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_model_name, "all-mpnet-base-v2")  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_max_concurrency, 4)  # pylint: disable=protected-access
        self.assertIsNone(gateway._section("qdrant", "missing"))  # pylint: disable=protected-access

        blank_model_gateway, *_ = _build_gateway(config=_make_config(encoder_model="   "))
        self.assertEqual(  # pylint: disable=protected-access
            blank_model_gateway._encoder_model_name,
            "all-mpnet-base-v2",
        )

        with self.assertRaisesRegex(RuntimeError, "qdrant.search.collection is required"):
            _build_gateway(config=_make_config(search_collection="  "))
        with self.assertRaisesRegex(RuntimeError, "qdrant.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=True))
        with self.assertRaisesRegex(RuntimeError, "qdrant.search.max_top_k"):
            _build_gateway(config=_make_config(max_top_k=0))
        with self.assertRaisesRegex(RuntimeError, "qdrant.search.snippet_max_chars"):
            _build_gateway(config=_make_config(snippet_max_chars=0))
        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            QdrantKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )

    def test_constructor_warnings_and_production_timeout_policy(self) -> None:
        logger = Mock()
        _build_gateway(
            config=_make_config(
                default_top_k=20,
                max_top_k=10,
                max_retries="bad",
                encoder_max_concurrency="bad",
            ),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "QdrantKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: Invalid max_retries configuration.",
            warnings,
        )

        logger = Mock()
        _build_gateway(
            config=_make_config(max_retries=-1),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "QdrantKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "QdrantKnowledgeGateway: Missing required production configuration field\\(s\\): timeout_seconds.",
        ):
            _build_gateway(config=_make_config(environment="production", timeout_seconds=None))

        gateway, *_ = _build_gateway(
            config=_make_config(environment="production", timeout_seconds=2.0),
        )
        self.assertEqual(gateway._api_timeout_seconds, 2.0)  # pylint: disable=protected-access

    def test_warn_missing_timeout_in_production_warns_when_called_directly(self) -> None:
        gateway = QdrantKnowledgeGateway.__new__(QdrantKnowledgeGateway)
        gateway._config = _make_config(  # pylint: disable=protected-access
            environment="production",
            timeout_seconds=None,
        )
        gateway._api_timeout_seconds = None  # pylint: disable=protected-access
        gateway._logging_gateway = Mock()  # pylint: disable=protected-access

        gateway._warn_missing_timeout_in_production()  # pylint: disable=protected-access

        gateway._logging_gateway.warning.assert_called_once_with(  # pylint: disable=protected-access
            "QdrantKnowledgeGateway: timeout_seconds is not configured in production."
        )

    def test_build_encoder_constructs_sentence_transformer(self) -> None:
        config = _make_config()
        gateway, _, _, _ = _build_gateway(config=config)
        with patch("mugen.core.gateway.knowledge.qdrant.SentenceTransformer") as transformer:
            built = gateway._build_encoder()  # pylint: disable=protected-access

            self.assertIs(built, transformer.return_value)
            transformer.assert_called_with(
                model_name_or_path="all-mpnet-base-v2",
                tokenizer_kwargs={"clean_up_tokenization_spaces": False},
                cache_folder="/tmp/hf",
            )

    def test_resolve_encoder_model_name_falls_back_for_invalid_values(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._config.qdrant.encoder.model = 123  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            gateway._resolve_encoder_model_name(),
            gateway._default_encoder_model,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.encoder.model = "   "  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            gateway._resolve_encoder_model_name(),
            gateway._default_encoder_model,  # pylint: disable=protected-access
        )

    async def test_check_readiness_requires_qdrant_url(self) -> None:
        gateway, client, _, _ = _build_gateway(config=_make_config())
        gateway._encoder = Mock()  # pylint: disable=protected-access
        await gateway.check_readiness()
        client.get_collections.assert_awaited_once_with()

        gateway._api_url = ""  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "requires qdrant.api.url"):
            await gateway.check_readiness()

    async def test_check_readiness_raises_when_probe_missing_or_failing(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "probe is unavailable"):
            await gateway.check_readiness()

        failing_client = SimpleNamespace(
            get_collections=AsyncMock(side_effect=RuntimeError("probe failed"))
        )
        failing_gateway, _, _, _ = _build_gateway(
            config=_make_config(),
            fake_client=failing_client,
        )
        with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
            await failing_gateway.check_readiness()

    async def test_check_readiness_raises_when_collection_not_found(self) -> None:
        fake_client = SimpleNamespace(
            get_collections=AsyncMock(
                return_value=SimpleNamespace(
                    collections=[SimpleNamespace(name="different")]
                )
            )
        )
        gateway, _, _, _ = _build_gateway(config=_make_config(), fake_client=fake_client)
        with self.assertRaisesRegex(RuntimeError, "configured collection was not found"):
            await gateway.check_readiness()

    async def test_check_readiness_raises_when_collection_payload_is_invalid(self) -> None:
        fake_client = SimpleNamespace(
            get_collections=AsyncMock(return_value=SimpleNamespace(collections={}))
        )
        gateway, _, _, _ = _build_gateway(config=_make_config(), fake_client=fake_client)
        with self.assertRaisesRegex(RuntimeError, "invalid payload"):
            await gateway.check_readiness()

    async def test_check_readiness_uses_internal_timeout_value_without_fallback(
        self,
    ) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config(timeout_seconds=2.5))
        gateway._api_timeout_seconds = 0  # pylint: disable=protected-access

        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.qdrant.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [0.0, 0.0])

    async def test_check_readiness_uses_default_timeout_when_value_unset(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config(timeout_seconds=2.5))
        gateway._api_timeout_seconds = None  # pylint: disable=protected-access

        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.qdrant.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [5.0, 5.0])

    async def test_check_readiness_raises_when_encoder_init_fails(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._get_encoder = AsyncMock(side_effect=RuntimeError("encoder failed"))  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

    async def test_get_encoder_builds_once_and_reuses_encoder(self) -> None:
        config = _make_config()
        gateway, _, _, _ = _build_gateway(config=config)
        built_encoder = object()
        with (
            patch.object(gateway, "_build_encoder", return_value=built_encoder) as build_encoder,
            patch(
                "mugen.core.gateway.knowledge.qdrant.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func: func()),
            ) as to_thread,
        ):
            first = await gateway._get_encoder()  # pylint: disable=protected-access
            second = await gateway._get_encoder()  # pylint: disable=protected-access

        self.assertIs(first, built_encoder)
        self.assertIs(second, built_encoder)
        build_encoder.assert_called_once()
        to_thread.assert_awaited_once()
        self.assertIs(to_thread.await_args.args[0], build_encoder)

    async def test_get_encoder_concurrent_first_calls_use_single_build(self) -> None:
        config = _make_config()
        gateway, _, _, _ = _build_gateway(config=config)
        built_encoder = object()

        async def _to_thread(func):
            await asyncio.sleep(0)
            return func()

        with (
            patch.object(gateway, "_build_encoder", return_value=built_encoder) as build_encoder,
            patch(
                "mugen.core.gateway.knowledge.qdrant.asyncio.to_thread",
                new=AsyncMock(side_effect=_to_thread),
            ) as to_thread,
        ):
            first, second = await asyncio.gather(
                gateway._get_encoder(),  # pylint: disable=protected-access
                gateway._get_encoder(),  # pylint: disable=protected-access
            )

        self.assertIs(first, built_encoder)
        self.assertIs(second, built_encoder)
        build_encoder.assert_called_once()
        to_thread.assert_awaited_once()

    async def test_get_encoder_handles_encoder_set_while_waiting_for_lock(self) -> None:
        config = _make_config()
        gateway, _, _, _ = _build_gateway(config=config)
        sentinel_encoder = object()
        gateway._encoder = None  # pylint: disable=protected-access

        class _InjectingLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                gateway._encoder = sentinel_encoder  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        gateway._encoder_lock = _InjectingLock()  # pylint: disable=protected-access
        resolved = await gateway._get_encoder()  # pylint: disable=protected-access
        self.assertIs(resolved, sentinel_encoder)

    async def test_encode_search_term_supports_vector_shapes(self) -> None:
        config = _make_config()
        gateway, _, _, _ = _build_gateway(config=config)

        gateway._encoder = SimpleNamespace(encode=lambda _term: _VectorLike())  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [1.0, 2.0],
        )

        gateway._encoder = SimpleNamespace(encode=lambda _term: [3, 4])  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [3.0, 4.0],
        )

        gateway._encoder = SimpleNamespace(encode=lambda _term: (5, 6))  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [5.0, 6.0],
        )

    def test_normalize_helpers(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())

        self.assertIsNone(gateway._normalize_optional_filter(" "))  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_optional_filter(" x "), "x")  # pylint: disable=protected-access

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            gateway._normalize_search_term(1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            gateway._normalize_search_term("   ")  # pylint: disable=protected-access

        tenant_id = uuid.uuid4()
        parsed_tenant_id = gateway._normalize_tenant_id(str(tenant_id))  # pylint: disable=protected-access
        self.assertEqual(parsed_tenant_id, str(tenant_id))
        self.assertEqual(  # pylint: disable=protected-access
            gateway._normalize_tenant_id(tenant_id),
            str(tenant_id),
        )
        with self.assertRaisesRegex(ValueError, "tenant_id must be a UUID"):
            gateway._normalize_tenant_id(1)  # pylint: disable=protected-access

        self.assertIsNone(gateway._normalize_min_similarity(None))  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_min_similarity(0.4), 0.4)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity("bad")  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity(2)  # pylint: disable=protected-access

        self.assertEqual(gateway._resolve_effective_top_k(None), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k("bad"), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k(999), 50)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k(-1), 1)  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "tenant_id"):
            gateway._normalize_uuid_text("bad-uuid", field_name="tenant_id")  # pylint: disable=protected-access

        snippet = gateway._build_snippet(  # pylint: disable=protected-access
            title="Short",
            body="abcdef",
        )
        self.assertEqual(snippet, "abcdef")

    async def test_low_level_branch_helpers(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())

        gateway._config.qdrant.api.url = 123  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_api_url(), "")  # pylint: disable=protected-access

        gateway._config.qdrant.api.key = 123  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._resolve_optional_api_string("key")  # pylint: disable=protected-access
        )
        gateway._config.qdrant.api.key = "   "  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._resolve_optional_api_string("key")  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity(float("nan"))  # pylint: disable=protected-access

        parsed_uuid = uuid.uuid4()
        self.assertEqual(
            gateway._normalize_uuid_text(parsed_uuid, field_name="tenant_id"),  # pylint: disable=protected-access
            str(parsed_uuid),
        )
        with self.assertRaisesRegex(RuntimeError, "tenant_id"):
            gateway._normalize_uuid_text(1, field_name="tenant_id")  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "tenant_id"):
            gateway._normalize_uuid_text(" ", field_name="tenant_id")  # pylint: disable=protected-access

        self.assertIsNone(gateway._coerce_optional_string(None))  # pylint: disable=protected-access
        self.assertEqual(gateway._coerce_optional_string(1), "1")  # pylint: disable=protected-access

        self.assertIsNone(gateway._coerce_float(None))  # pylint: disable=protected-access
        self.assertIsNone(gateway._coerce_float("bad"))  # pylint: disable=protected-access

        self.assertIsNone(
            gateway._build_snippet(title=None, body=None)  # pylint: disable=protected-access
        )
        gateway._snippet_max_chars = 3  # pylint: disable=protected-access
        self.assertEqual(
            gateway._build_snippet(  # pylint: disable=protected-access
                title="abcde",
                body=None,
            ),
            "abc",
        )

        names = gateway._extract_collection_names(  # pylint: disable=protected-access
            {"collections": [{"name": 1}, {"name": "ok"}]}
        )
        self.assertEqual(names, {"ok"})

        payload_dict, score_dict = gateway._extract_point_payload_and_score(  # pylint: disable=protected-access
            {"payload": {"k": "v"}, "score": 0.8}
        )
        self.assertEqual(payload_dict, {"k": "v"})
        self.assertEqual(score_dict, 0.8)
        payload_fallback, score_fallback = gateway._extract_point_payload_and_score(  # pylint: disable=protected-access
            {"id": "x", "score": 0.7}
        )
        self.assertEqual(payload_fallback, {"id": "x", "score": 0.7})
        self.assertEqual(score_fallback, 0.7)

        with self.assertRaisesRegex(RuntimeError, "hit payload is invalid"):
            gateway._extract_point_payload_and_score(object())  # pylint: disable=protected-access

        class _ModelDumpNonDict:
            def model_dump(self):
                return []

        class _ModelDumpBadPayload:
            def model_dump(self):
                return {"payload": "bad", "score": 0.1}

        with self.assertRaisesRegex(RuntimeError, "hit payload is invalid"):
            gateway._extract_point_payload_and_score(_ModelDumpNonDict())  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "hit payload is invalid"):
            gateway._extract_point_payload_and_score(_ModelDumpBadPayload())  # pylint: disable=protected-access

        async def _sync_call():
            result = await gateway._call_provider_method(  # pylint: disable=protected-access
                lambda x: x,
                "ok",
            )
            self.assertEqual(result, "ok")

        await _sync_call()

    def test_build_query_filter(self) -> None:
        gateway, *_ = _build_gateway(config=_make_config())
        parsed_uuid = str(uuid.uuid4())
        query_filter = gateway._build_query_filter(  # pylint: disable=protected-access
            tenant_id=parsed_uuid,
            channel="web",
            locale="en",
            category="billing",
        )
        self.assertEqual(len(query_filter.must), 4)
        self.assertEqual(query_filter.must[0].key, "tenant_id")
        self.assertEqual(query_filter.must[0].match.value, parsed_uuid)

    def test_extract_collection_names_supports_multiple_shapes(self) -> None:
        from_dict = QdrantKnowledgeGateway._extract_collection_names(  # pylint: disable=protected-access
            {
                "collections": [
                    {"name": "a"},
                    "b",
                ]
            }
        )
        self.assertEqual(from_dict, {"a", "b"})

        with self.assertRaisesRegex(RuntimeError, "invalid payload"):
            QdrantKnowledgeGateway._extract_collection_names(  # pylint: disable=protected-access
                {"collections": {}}
            )

    def test_normalise_items_validation_and_threshold(self) -> None:
        gateway, *_ = _build_gateway(config=_make_config())
        payload = _payload()
        items = gateway._normalise_items(  # pylint: disable=protected-access
            search_result=[_PointObject(payload=payload, score=0.9)],
            min_similarity=0.8,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["similarity"], 0.9)
        self.assertIsNone(items[0]["distance"])

        filtered = gateway._normalise_items(  # pylint: disable=protected-access
            search_result=[_PointObject(payload=payload, score=0.4)],
            min_similarity=0.8,
        )
        self.assertEqual(filtered, [])

        with self.assertRaisesRegex(RuntimeError, "missing required key"):
            gateway._normalise_items(  # pylint: disable=protected-access
                search_result=[_PointObject(payload={"tenant_id": str(uuid.uuid4())}, score=0.5)],
                min_similarity=None,
            )

        bad_payload = _payload(tenant_id="bad-uuid")
        with self.assertRaisesRegex(RuntimeError, "tenant_id"):
            gateway._normalise_items(  # pylint: disable=protected-access
                search_result=[_PointObject(payload=bad_payload, score=0.5)],
                min_similarity=None,
            )

    async def test_request_timeout_kwargs_and_query_collection_paths(self) -> None:
        gateway, fake_client, _, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        self.assertEqual(gateway._request_timeout_kwargs(), {})  # pylint: disable=protected-access

        gateway._api_timeout_seconds = 1.25  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            gateway._request_timeout_kwargs(),
            {"timeout": 1.25},
        )

        fake_client.search = AsyncMock(return_value=[_PointObject(payload=_payload(), score=0.3)])
        points = await gateway._query_collection(  # pylint: disable=protected-access
            query_vector=[0.1],
            query_filter=gateway._build_query_filter(  # pylint: disable=protected-access
                tenant_id=str(uuid.uuid4()),
                channel=None,
                locale=None,
                category=None,
            ),
            top_k=2,
        )
        self.assertEqual(len(points), 1)

        fake_client.search = AsyncMock(return_value={})
        with self.assertRaisesRegex(RuntimeError, "invalid search payload"):
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1],
                query_filter=gateway._build_query_filter(  # pylint: disable=protected-access
                    tenant_id=str(uuid.uuid4()),
                    channel=None,
                    locale=None,
                    category=None,
                ),
                top_k=2,
            )

        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "search API is unavailable"):
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1],
                query_filter=gateway._build_query_filter(  # pylint: disable=protected-access
                    tenant_id=str(uuid.uuid4()),
                    channel=None,
                    locale=None,
                    category=None,
                ),
                top_k=2,
            )

    async def test_execute_with_retry_success_and_exhaustion_paths(self) -> None:
        gateway, _, logging_gateway, _ = _build_gateway(config=_make_config())

        gateway._api_max_retries = 2  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.1  # pylint: disable=protected-access
        request_factory = AsyncMock(side_effect=[asyncio.TimeoutError(), "ok"])
        with patch("mugen.core.gateway.knowledge.qdrant.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=request_factory,
            )

        self.assertEqual(result, "ok")
        self.assertEqual(request_factory.await_count, 2)
        sleep.assert_awaited_once_with(0.1)
        self.assertTrue(logging_gateway.warning.called)

        gateway._api_max_retries = 1  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.0  # pylint: disable=protected-access
        failing_factory = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch("mugen.core.gateway.knowledge.qdrant.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(asyncio.TimeoutError):
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=failing_factory,
                )
            sleep.assert_not_awaited()

    async def test_execute_with_retry_propagates_non_transient_errors(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._api_max_retries = 2  # pylint: disable=protected-access
        request_factory = AsyncMock(side_effect=ValueError("bad request"))
        with self.assertRaises(ValueError):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=request_factory,
            )

    async def test_execute_with_retry_handles_zero_attempt_window_defensively(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        request_factory = AsyncMock()
        with patch("builtins.max", return_value=-1):
            result = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=request_factory,
            )
        self.assertIsNone(result)
        request_factory.assert_not_awaited()

    async def test_search_success_and_failure_paths(self) -> None:
        tenant_id = uuid.uuid4()
        payload = _payload(tenant_id=str(tenant_id))
        fake_client = SimpleNamespace(
            search=AsyncMock(return_value=[_PointObject(payload=payload, score=0.9)]),
            get_collections=AsyncMock(
                return_value=SimpleNamespace(
                    collections=[SimpleNamespace(name="downstream_kp_search_doc")]
                )
            ),
        )
        gateway, _client, logger, _ = _build_gateway(
            config=_make_config(timeout_seconds=2.5),
            fake_client=fake_client,
        )
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # pylint: disable=protected-access

        result = await gateway.search(
            QdrantSearchVendorParams(
                search_term="hello world",
                tenant_id=tenant_id,
                top_k=5,
                min_similarity=0.8,
                channel="web",
                locale="en-US",
                category="billing",
            )
        )

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.raw_vendor["provider"], "qdrant")
        self.assertEqual(result.raw_vendor["collection"], "downstream_kp_search_doc")
        self.assertEqual(result.raw_vendor["top_k"], 5)
        self.assertEqual(result.raw_vendor["min_similarity"], 0.8)

        search_kwargs = fake_client.search.await_args.kwargs
        self.assertEqual(search_kwargs["collection_name"], "downstream_kp_search_doc")
        self.assertEqual(search_kwargs["limit"], 5)
        self.assertEqual(search_kwargs["timeout"], 2.5)
        tenant_condition = search_kwargs["query_filter"].must[0]
        self.assertEqual(tenant_condition.key, "tenant_id")
        self.assertEqual(tenant_condition.match.value, str(tenant_id))

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            await gateway.search(
                QdrantSearchVendorParams(
                    search_term=123,  # type: ignore[arg-type]
                    tenant_id=tenant_id,
                )
            )

        fake_client.search = AsyncMock(return_value=[_PointObject(payload=payload, score=0.2)])
        filtered = await gateway.search(
            QdrantSearchVendorParams(
                search_term="hello world",
                tenant_id=tenant_id,
                min_similarity=0.8,
            )
        )
        self.assertEqual(filtered.items, [])

        gateway._execute_with_retry = AsyncMock(  # pylint: disable=protected-access
            side_effect=RuntimeError("transport")
        )
        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(
                QdrantSearchVendorParams(
                    search_term="hello",
                    tenant_id=tenant_id,
                )
            )
        self.assertEqual(raised.exception.provider, "qdrant")
        self.assertEqual(raised.exception.operation, "search")
        logger.warning.assert_any_call(
            "QdrantKnowledgeGateway transport failure "
            "(operation=search error=RuntimeError: transport)"
        )

    async def test_search_uses_default_top_k_when_not_set(self) -> None:
        tenant_id = uuid.uuid4()
        payload = _payload(tenant_id=str(tenant_id))
        fake_client = SimpleNamespace(
            search=AsyncMock(return_value=[_PointWithModelDump(payload=payload, score=0.9)]),
            get_collections=AsyncMock(
                return_value=SimpleNamespace(
                    collections=[SimpleNamespace(name="downstream_kp_search_doc")]
                )
            ),
        )
        gateway, *_ = _build_gateway(config=_make_config(default_top_k=7), fake_client=fake_client)
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # pylint: disable=protected-access

        await gateway.search(
            QdrantSearchVendorParams(
                search_term="hello",
                tenant_id=tenant_id,
                top_k=None,  # type: ignore[arg-type]
            )
        )
        self.assertEqual(fake_client.search.await_args.kwargs["limit"], 7)

    async def test_aclose_and_assert_open(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())

        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        self.assertIsNone(await gateway.aclose())

        close_calls: list[str] = []

        def _sync_close():
            close_calls.append("sync")
            return None

        async def _async_close():
            close_calls.append("async")
            return None

        gateway._closed = False  # pylint: disable=protected-access
        gateway._client = SimpleNamespace(close=_sync_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway._closed = False  # pylint: disable=protected-access
        gateway._client = SimpleNamespace(close=_async_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        self.assertEqual(close_calls, ["sync", "async"])

        with self.assertRaisesRegex(RuntimeError, "is closed"):
            gateway._assert_open()  # pylint: disable=protected-access


if __name__ == "__main__":
    unittest.main()
