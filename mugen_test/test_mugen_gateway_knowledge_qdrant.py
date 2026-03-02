"""Unit tests for mugen.core.gateway.knowledge.qdrant.QdrantKnowledgeGateway."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.dto.qdrant.search import QdrantSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.qdrant import QdrantKnowledgeGateway


def _make_config(
    *,
    environment: str = "development",
    timeout_seconds: object = 2.5,
    max_retries: object = 1,
    retry_backoff_seconds: object = 0.0,
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
            encoder=SimpleNamespace(
                max_concurrency=encoder_max_concurrency,
            ),
        ),
        transformers=SimpleNamespace(hf=SimpleNamespace(home="/tmp/hf")),
    )


def _build_gateway(
    *,
    config: SimpleNamespace,
    logging_gateway: Mock | None = None,
    fake_client: SimpleNamespace | None = None,
):
    logger = logging_gateway or Mock()
    client = fake_client or SimpleNamespace(
        count=AsyncMock(),
        search=AsyncMock(),
        get_collections=AsyncMock(return_value=SimpleNamespace(collections=[])),
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


class _WithModelDump:
    def model_dump(self):
        return {"id": 1}


class _WithDictMethod:
    def dict(self):
        return {"id": 2}


class _WithNonDictDumpAndDict:
    def __init__(self) -> None:
        self.value = 11

    def model_dump(self):
        return ["not", "dict"]

    def dict(self):
        return ["still-not-dict"]


class _CountObject:
    def __init__(self, count: int) -> None:
        self.count = count


class TestMugenGatewayKnowledgeQdrant(unittest.IsolatedAsyncioTestCase):
    """Covers timeout parsing, retry behavior, and search flow branches."""

    async def test_check_readiness_requires_qdrant_url(self) -> None:
        gateway, client, _, _ = _build_gateway(config=_make_config())
        gateway._encoder = Mock()  # pylint: disable=protected-access
        await gateway.check_readiness()
        client.get_collections.assert_awaited_once_with()

        gateway._config.qdrant.api.url = ""  # pylint: disable=protected-access
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

    async def test_check_readiness_defaults_timeout_when_nonpositive(self) -> None:
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

        self.assertEqual(timeout_values, [5.0, 5.0])

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

    async def test_check_readiness_blocks_on_encoder_initialization(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._get_encoder = AsyncMock(return_value=object())  # pylint: disable=protected-access
        await gateway.check_readiness()
        gateway._get_encoder.assert_awaited_once_with()  # pylint: disable=protected-access

    async def test_check_readiness_raises_when_encoder_init_fails(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())
        gateway._get_encoder = AsyncMock(side_effect=RuntimeError("encoder failed"))  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

    async def test_aclose_handles_missing_sync_and_async_client_close(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config())

        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        close_calls: list[str] = []

        def _sync_close():
            close_calls.append("sync")
            return None

        gateway._client = SimpleNamespace(close=_sync_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        async def _async_close():
            close_calls.append("async")
            return None

        gateway._client = SimpleNamespace(close=_async_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        self.assertEqual(close_calls, ["sync", "async"])

    def test_parse_helpers_cover_invalid_and_edge_values(self) -> None:
        config = _make_config()
        gateway, _, logging_gateway, _ = _build_gateway(config=config)

        gateway._config.qdrant.encoder.max_concurrency = "bad"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_max_concurrency(),  # pylint: disable=protected-access
            gateway._default_encoder_max_concurrency,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.encoder.max_concurrency = 0  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_max_concurrency(),  # pylint: disable=protected-access
            gateway._default_encoder_max_concurrency,  # pylint: disable=protected-access
        )

        gateway._config.qdrant.api.timeout_seconds = "bad"  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_api_timeout_seconds())  # pylint: disable=protected-access
        gateway._config.qdrant.api.timeout_seconds = 0  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_api_timeout_seconds())  # pylint: disable=protected-access
        gateway._config.qdrant.api.timeout_seconds = 3  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_api_timeout_seconds(), 3.0)  # pylint: disable=protected-access

        gateway._config.qdrant.api.max_retries = "bad"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_api_max_retries(),  # pylint: disable=protected-access
            gateway._default_api_max_retries,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.api.max_retries = -1  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_api_max_retries(),  # pylint: disable=protected-access
            gateway._default_api_max_retries,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.api.max_retries = 4  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_api_max_retries(), 4)  # pylint: disable=protected-access

        gateway._config.qdrant.api.retry_backoff_seconds = "bad"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_api_retry_backoff_seconds(),  # pylint: disable=protected-access
            gateway._default_api_retry_backoff_seconds,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.api.retry_backoff_seconds = -1  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_api_retry_backoff_seconds(),  # pylint: disable=protected-access
            gateway._default_api_retry_backoff_seconds,  # pylint: disable=protected-access
        )
        gateway._config.qdrant.api.retry_backoff_seconds = 0.25  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_api_retry_backoff_seconds(), 0.25  # pylint: disable=protected-access
        )

        warnings = [str(call.args[0]) for call in logging_gateway.warning.call_args_list]
        self.assertIn(
            "QdrantKnowledgeGateway: Invalid timeout_seconds configuration.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: timeout_seconds must be positive when provided.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: Invalid max_retries configuration.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: Invalid retry_backoff_seconds configuration.",
            warnings,
        )
        self.assertIn(
            "QdrantKnowledgeGateway: retry_backoff_seconds must be non-negative.",
            warnings,
        )

    def test_fail_fast_when_timeout_missing_in_production_only(self) -> None:
        dev_config = _make_config(environment="development", timeout_seconds=None)
        _, _, dev_logger, _ = _build_gateway(config=dev_config)
        self.assertFalse(dev_logger.warning.called)

        prod_config = _make_config(environment="production", timeout_seconds=None)
        with self.assertRaisesRegex(
            RuntimeError,
            "QdrantKnowledgeGateway: Missing required production configuration field\\(s\\): timeout_seconds.",
        ):
            _build_gateway(config=prod_config)

        prod_with_timeout = _make_config(environment="production", timeout_seconds=2.0)
        _, _, prod_timeout_logger, _ = _build_gateway(config=prod_with_timeout)
        prod_timeout_logger.warning.assert_not_called()

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

    def test_vendor_and_count_normalizers_cover_all_shapes(self) -> None:
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item({"x": 1}),  # pylint: disable=protected-access
            {"x": 1},
        )
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item(_WithModelDump()),  # pylint: disable=protected-access
            {"id": 1},
        )
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item(_WithDictMethod()),  # pylint: disable=protected-access
            {"id": 2},
        )
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item(_WithNonDictDumpAndDict()),  # pylint: disable=protected-access
            {"value": 11},
        )
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item(SimpleNamespace(value=3)),  # pylint: disable=protected-access
            {"value": 3},
        )
        self.assertEqual(
            QdrantKnowledgeGateway._normalise_vendor_item(7),  # pylint: disable=protected-access
            {"value": "7"},
        )

        self.assertEqual(QdrantKnowledgeGateway._count_result(8), 8)  # pylint: disable=protected-access
        self.assertEqual(
            QdrantKnowledgeGateway._count_result({"count": 9}),  # pylint: disable=protected-access
            9,
        )
        self.assertEqual(
            QdrantKnowledgeGateway._count_result(_CountObject(10)),  # pylint: disable=protected-access
            10,
        )
        self.assertIsNone(
            QdrantKnowledgeGateway._count_result({"count": "x"})  # pylint: disable=protected-access
        )
        self.assertIsNone(QdrantKnowledgeGateway._count_result("nope"))  # pylint: disable=protected-access

    async def test_request_timeout_kwargs_covers_none_and_value(self) -> None:
        gateway, _, _, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        self.assertEqual(gateway._request_timeout_kwargs(), {})  # pylint: disable=protected-access
        gateway._api_timeout_seconds = 1.25  # pylint: disable=protected-access
        self.assertEqual(
            gateway._request_timeout_kwargs(),  # pylint: disable=protected-access
            {"timeout": 1.25},
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
                    operation="count",
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

    async def test_search_count_applies_timeout_and_retries(self) -> None:
        config = _make_config(timeout_seconds=2.5, max_retries=1, retry_backoff_seconds=0.0)
        fake_client = SimpleNamespace(
            count=AsyncMock(
                side_effect=[
                    asyncio.TimeoutError(),
                    {"count": 3},
                ]
            ),
            search=AsyncMock(),
        )
        gateway, _, _, _ = _build_gateway(config=config, fake_client=fake_client)

        result = await gateway.search(
            QdrantSearchVendorParams(
                collection_name="test_collection",
                search_term="hello",
                count=True,
                strategy="must",
                dataset="docs",
                date_to="2025-01-31T00:00:00Z",
                keywords=["policy"],
            )
        )

        self.assertEqual(result.total_count, 3)
        self.assertEqual(fake_client.count.await_count, 2)
        self.assertEqual(fake_client.count.await_args_list[0].kwargs["timeout"], 2.5)

    async def test_search_should_count_with_date_window(self) -> None:
        fake_client = SimpleNamespace(
            count=AsyncMock(return_value=SimpleNamespace(count=7)),
            search=AsyncMock(),
        )
        gateway, _, _, _ = _build_gateway(config=_make_config(), fake_client=fake_client)

        result = await gateway.search(
            QdrantSearchVendorParams(
                collection_name="collection_a",
                search_term="hello",
                strategy="should",
                count=True,
                dataset="kb",
                date_from="2025-01-01T00:00:00Z",
                date_to="2025-01-31T00:00:00Z",
                keywords=["alpha"],
            )
        )

        self.assertEqual(result.items, [])
        self.assertEqual(result.total_count, 7)
        self.assertIsInstance(result.raw_vendor, dict)
        self.assertEqual(fake_client.search.await_count, 0)

    async def test_search_should_non_count_uses_encoder_and_returns_normalized_items(
        self,
    ) -> None:
        fake_client = SimpleNamespace(
            count=AsyncMock(),
            search=AsyncMock(return_value=[_WithModelDump(), _WithDictMethod()]),
        )
        gateway, _, _, _ = _build_gateway(config=_make_config(), fake_client=fake_client)
        gateway._encoder = SimpleNamespace(encode=lambda _term: [0.1, 0.2])  # pylint: disable=protected-access

        result = await gateway.search(
            QdrantSearchVendorParams(
                collection_name="collection_b",
                search_term="hello",
                strategy="should",
                count=False,
                dataset="kb",
                date_from="2025-01-01T00:00:00Z",
                keywords=["beta"],
                limit=3,
            )
        )

        self.assertEqual(result.total_count, None)
        self.assertEqual(result.items, [{"id": 1}, {"id": 2}])
        self.assertEqual(result.raw_vendor, {"strategy": "should", "count": False})
        self.assertEqual(fake_client.search.await_count, 1)

    async def test_search_must_non_count_with_dataset_filter(self) -> None:
        fake_client = SimpleNamespace(
            count=AsyncMock(),
            search=AsyncMock(return_value=[{"id": "a"}]),
        )
        gateway, _, _, _ = _build_gateway(config=_make_config(), fake_client=fake_client)
        gateway._encoder = SimpleNamespace(encode=lambda _term: [0.5])  # pylint: disable=protected-access

        result = await gateway.search(
            QdrantSearchVendorParams(
                collection_name="collection_c",
                search_term="hello",
                strategy="must",
                count=False,
                dataset="kb",
                keywords=["gamma"],
                limit=2,
            )
        )

        self.assertEqual(result.total_count, None)
        self.assertEqual(result.items, [{"id": "a"}])
        self.assertEqual(result.raw_vendor, {"strategy": "must", "count": False})

    async def test_search_raises_runtime_error_when_retry_budget_exhausted(self) -> None:
        config = _make_config(max_retries=2)
        fake_client = SimpleNamespace(
            count=AsyncMock(side_effect=asyncio.TimeoutError()),
            search=AsyncMock(),
        )
        gateway, _, _, _ = _build_gateway(config=config, fake_client=fake_client)

        with self.assertRaises(KnowledgeGatewayRuntimeError) as exc:
            await gateway.search(
                QdrantSearchVendorParams(
                    collection_name="test_collection",
                    search_term="hello",
                    count=True,
                )
            )

        self.assertEqual(exc.exception.provider, "qdrant")
        self.assertEqual(exc.exception.operation, "count")
        self.assertIsInstance(exc.exception.cause, asyncio.TimeoutError)
        self.assertEqual(fake_client.count.await_count, 3)


if __name__ == "__main__":
    unittest.main()
