"""Unit tests for mugen.core.plugin.acp.api.func_runtime_matrix."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.acp.api import func_runtime_matrix


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


class TestMugenAcpFuncRuntimeMatrix(unittest.IsolatedAsyncioTestCase):
    """Covers Matrix runtime device verification ACP endpoint behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            matrix_client="matrix-client",
            logging_gateway="logger",
        )
        with patch.object(func_runtime_matrix.di, "container", new=container):
            self.assertEqual(
                func_runtime_matrix._matrix_client_provider(),
                "matrix-client",
            )
            self.assertEqual(func_runtime_matrix._logger_provider(), "logger")

    async def test_endpoint_lists_active_runtime_profiles(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    {
                        "client_profile_id": "profile-a",
                        "client_profile_key": "default",
                        "recipient_user_id": "@bot:example.com",
                        "public_name": "device-a",
                        "session_id": "DEV-A",
                        "session_key": "ABCD 1234",
                    }
                ]
            )
        )
        logger = Mock()

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={}),
        ):
            response = await endpoint(
                matrix_client_provider=lambda: matrix_client,
                logger_provider=lambda: logger,
                auth_user="user-id",
            )

        self.assertEqual(
            response,
            {
                "value": [
                    {
                        "client_profile_id": "profile-a",
                        "client_profile_key": "default",
                        "recipient_user_id": "@bot:example.com",
                        "public_name": "device-a",
                        "session_id": "DEV-A",
                        "session_key": "ABCD 1234",
                    }
                ]
            },
        )
        matrix_client.active_device_verification_data.assert_awaited_once_with(
            client_profile_id=None
        )

    async def test_endpoint_filters_one_client_profile(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(
                return_value=[
                    {
                        "client_profile_id": client_profile_id,
                        "client_profile_key": "default",
                        "recipient_user_id": "@bot:example.com",
                        "public_name": "device-a",
                        "session_id": "DEV-A",
                        "session_key": "ABCD 1234",
                    }
                ]
            )
        )

        with patch.object(
            func_runtime_matrix,
            "request",
            new=SimpleNamespace(args={"client_profile_id": f" {client_profile_id} "}),
        ):
            response = await endpoint(
                matrix_client_provider=lambda: matrix_client,
                logger_provider=lambda: Mock(),
                auth_user="user-id",
            )

        self.assertEqual(response["value"][0]["client_profile_id"], client_profile_id)
        matrix_client.active_device_verification_data.assert_awaited_once_with(
            client_profile_id=client_profile_id
        )

    async def test_endpoint_rejects_invalid_client_profile_filter(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        logger = Mock()

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": "bad-uuid"}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    matrix_client_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: logger,
                    auth_user="user-id",
                )

        self.assertEqual(ex.exception.code, 400)
        logger.debug.assert_called_once_with(
            "Invalid Matrix device verification client_profile_id filter."
        )

    async def test_endpoint_returns_404_for_missing_active_profile(self) -> None:
        endpoint = func_runtime_matrix.matrix_device_verification_data.__wrapped__
        client_profile_id = "00000000-0000-0000-0000-000000000123"
        logger = Mock()
        matrix_client = SimpleNamespace(
            active_device_verification_data=AsyncMock(return_value=[])
        )

        with (
            patch.object(func_runtime_matrix, "abort", side_effect=_abort_raiser),
            patch.object(
                func_runtime_matrix,
                "request",
                new=SimpleNamespace(args={"client_profile_id": client_profile_id}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    matrix_client_provider=lambda: matrix_client,
                    logger_provider=lambda: logger,
                    auth_user="user-id",
                )

        self.assertEqual(ex.exception.code, 404)

    async def test_collect_device_verification_data_falls_back_to_single_client(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
            SimpleNamespace(
                device_verification_data=Mock(
                    return_value={
                        "client_profile_id": "profile-a",
                        "client_profile_key": "default",
                        "recipient_user_id": "@bot:example.com",
                        "public_name": "device-a",
                        "session_id": "DEV-A",
                        "session_key": "ABCD 1234",
                        "ignored": "value",
                    }
                )
            ),
            client_profile_id="profile-a",
            )
        )

        self.assertEqual(
            entries,
            [
                {
                    "client_profile_id": "profile-a",
                    "client_profile_key": "default",
                    "recipient_user_id": "@bot:example.com",
                    "public_name": "device-a",
                    "session_id": "DEV-A",
                    "session_key": "ABCD 1234",
                }
            ],
        )

    async def test_collect_device_verification_data_returns_empty_without_resolver(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(),
                client_profile_id=None,
            )
        )

        self.assertEqual(entries, [])

    async def test_collect_device_verification_data_rejects_invalid_single_entry(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(
                    device_verification_data=Mock(
                        return_value={"client_profile_key": "default"}
                    )
                ),
                client_profile_id=None,
            )
        )

        self.assertEqual(entries, [])

    async def test_collect_device_verification_data_rejects_mismatched_profile(
        self,
    ) -> None:
        entries = await (  # pylint: disable=protected-access
            func_runtime_matrix._collect_device_verification_data(
                SimpleNamespace(
                    device_verification_data=Mock(
                        return_value={
                            "client_profile_id": "profile-a",
                            "client_profile_key": "default",
                        }
                    )
                ),
                client_profile_id="profile-b",
            )
        )

        self.assertEqual(entries, [])

    def test_normalize_entries_and_entry_reject_invalid_values(self) -> None:
        self.assertEqual(
            func_runtime_matrix._normalize_entries(  # pylint: disable=protected-access
                None
            ),
            [],
        )
        self.assertEqual(
            func_runtime_matrix._normalize_entries(  # pylint: disable=protected-access
                [
                    {"client_profile_key": "default"},
                    "bad-row",
                ]
            ),
            [],
        )
        self.assertIsNone(
            func_runtime_matrix._normalize_entry(  # pylint: disable=protected-access
                "bad-row"
            )
        )
        self.assertIsNone(
            func_runtime_matrix._normalize_entry(  # pylint: disable=protected-access
                {"client_profile_id": "  "}
            )
        )
