"""Unit tests for authenticated runtime extension status endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from quart import Quart

from mugen.bootstrap_state import get_extension_statuses
from mugen.core.plugin.acp.api import func_runtime_extensions


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None) -> None:
    raise _AbortCalled(code, message)


def _status(token: str, status: str) -> dict[str, object]:
    return {
        "token": token,
        "extension_type": "fw",
        "configured": status != "absent",
        "enabled": status not in {"absent", "disabled"},
        "available": status == "registered",
        "status": status,
        "reason": None if status == "registered" else "safe_reason",
        "exception": "must never be exposed",
    }


class TestMugenAcpFuncRuntimeExtensions(unittest.IsolatedAsyncioTestCase):
    """Covers extension status collection and detail contracts."""

    async def test_status_provider_uses_current_app_bootstrap_snapshot(self) -> None:
        app = Quart("runtime-extension-provider")
        async with app.app_context():
            statuses = get_extension_statuses(app)
            statuses["core.fw.billing"] = _status(
                "core.fw.billing",
                "registered",
            )
            self.assertIs(
                func_runtime_extensions._extension_status_provider(),
                statuses,
            )

    async def test_collection_is_sorted_and_sanitized(self) -> None:
        statuses = {
            "downstream.fw.example": _status(
                "downstream.fw.example",
                "failed",
            ),
            "core.fw.billing": _status("core.fw.billing", "registered"),
        }
        endpoint = func_runtime_extensions.runtime_extensions.__wrapped__

        result = await endpoint(status_provider=lambda: statuses)

        self.assertEqual(
            [row["token"] for row in result["value"]],
            ["core.fw.billing", "downstream.fw.example"],
        )
        self.assertNotIn("exception", result["value"][1])
        self.assertEqual(
            set(result["value"][0]),
            {
                "token",
                "extension_type",
                "configured",
                "enabled",
                "available",
                "status",
                "reason",
            },
        )

    async def test_detail_normalizes_token_and_rejects_unknown_token(self) -> None:
        statuses = {
            "core.fw.billing": _status("core.fw.billing", "disabled"),
        }
        endpoint = func_runtime_extensions.runtime_extension.__wrapped__

        result = await endpoint(
            token=" CORE.FW.BILLING ",
            status_provider=lambda: statuses,
        )
        self.assertEqual(result["token"], "core.fw.billing")
        self.assertNotIn("exception", result)

        with patch.object(
            func_runtime_extensions,
            "abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as raised:
                await endpoint(
                    token="unknown.extension",
                    status_provider=lambda: statuses,
                )
        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(raised.exception.message, "Extension token not found.")
