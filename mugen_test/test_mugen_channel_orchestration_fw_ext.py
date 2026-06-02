"""Coverage tests for mugen.core.plugin.channel_orchestration.fw_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mugen.core.plugin.channel_orchestration.fw_ext as fw_ext_module
from mugen.core.plugin.channel_orchestration.fw_ext import (
    ChannelOrchestrationFWExtension,
)


class TestMugenChannelOrchestrationFWExtension(unittest.IsolatedAsyncioTestCase):
    """Exercise provider, setup, and table-registration paths."""

    async def test_setup_registers_handoff_service(self) -> None:
        container = SimpleNamespace(
            relational_storage_gateway="rsg",
            register_ext_service=Mock(),
        )
        handoff_service_ctor = Mock(return_value="handoff-service")

        with (
            patch.object(fw_ext_module.di, "container", new=container),
            patch.object(
                fw_ext_module,
                "HumanHandoffSessionService",
                handoff_service_ctor,
            ),
        ):
            self.assertEqual(fw_ext_module._rsg_provider(), "rsg")
            ext = ChannelOrchestrationFWExtension()
            self.assertEqual(ext.platforms, [])
            await ext.setup(app=Mock())

        handoff_service_ctor.assert_called_once_with(
            table=fw_ext_module._HUMAN_HANDOFF_TABLE,
            rsg="rsg",
        )
        container.register_ext_service.assert_called_once_with(
            fw_ext_module.di.EXT_SERVICE_HUMAN_HANDOFF,
            "handoff-service",
            override=True,
        )

    async def test_register_runtime_tables_handles_non_sqla_and_value_error(
        self,
    ) -> None:
        ext = ChannelOrchestrationFWExtension(rsg_provider=lambda: object())
        ext._register_runtime_tables()  # pylint: disable=protected-access

        class _Gateway:
            def __init__(self, *, side_effect=None) -> None:
                self.register_tables = Mock(side_effect=side_effect)

        with patch.object(
            fw_ext_module,
            "SQLAlchemyRelationalStorageGateway",
            _Gateway,
        ):
            gateway = _Gateway()
            ext = ChannelOrchestrationFWExtension(rsg_provider=lambda: gateway)
            ext._register_runtime_tables()  # pylint: disable=protected-access
            gateway.register_tables.assert_called_once_with(
                {
                    fw_ext_module._HUMAN_HANDOFF_TABLE: (
                        fw_ext_module.HumanHandoffSession.__table__
                    )
                }
            )

            failing_gateway = _Gateway(side_effect=ValueError("already registered"))
            ext = ChannelOrchestrationFWExtension(
                rsg_provider=lambda: failing_gateway
            )
            ext._register_runtime_tables()  # pylint: disable=protected-access
            failing_gateway.register_tables.assert_called_once()


if __name__ == "__main__":
    unittest.main()
