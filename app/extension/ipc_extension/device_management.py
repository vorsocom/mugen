"""Provides an implementation of IIPCExtension to manage devices."""

__all__ = ["DeviceManagementIPCExtension"]

import textwrap
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide
from nio import AsyncClient

from app.core.contract.ipc_extension import IIPCExtension
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.di import DIContainer


class DeviceManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage devices."""

    @inject
    def __init__(
        self,
        config: dict = Provide[DIContainer.config],
        client: AsyncClient = Provide[DIContainer.client],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._client = client
        self._logging_gateway = logging_gateway

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "get_device_verification_data",
        ]

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.debug(
            "DeviceManagementIPCExtension: Executing command:"
            f" {payload['data']['command']}"
        )
        match payload["data"]["command"]:
            case "get_device_verification_data":
                await self._get_device_verification_data(payload)
                return
            case _:
                ...

    async def _get_device_verification_data(self, payload: dict) -> None:
        """Get the assistant device's verification data."""
        session_key = " ".join(
            textwrap.wrap(self._client.olm.account.identity_keys["ed25519"], 4)
        )
        await payload["response_queue"].put(
            {
                "response": {
                    "data": {
                        "public_name": self._config.matrix_client_device_name,
                        "session_id": self._client.device_id,
                        "session_key": session_key,
                    },
                },
            },
        )
