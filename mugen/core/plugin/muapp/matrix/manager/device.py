"""Provides an implementation of IIPCExtension to manage devices."""

__all__ = ["DeviceManagementIPCExtension"]

import textwrap

from dependency_injector import providers
from dependency_injector.wiring import inject, Provide

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.di import DIContainer


class DeviceManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage devices."""

    @inject
    def __init__(  # pylint: disable=super-init-not-called
        self,
        config: providers.Configuration = Provide[  # pylint: disable=c-extension-no-member
            DIContainer.config.delegate()
        ],
        matrix_client: IMatrixClient = Provide[DIContainer.matrix_client],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
    ) -> None:
        self._client = matrix_client
        self._config = config
        self._logging_gateway = logging_gateway

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "matrix_get_device_verification_data",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["matrix"]

    def platform_supported(self, platform: str) -> bool:
        """Determine if the extension supports the specified platform."""
        return not self.platforms or platform in self.platforms

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.debug(
            f"DeviceManagementIPCExtension: Executing command: {payload['command']}"
        )
        match payload["data"]["command"]:
            case "matrix_get_device_verification_data":
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
                        "public_name": self._config.matrix.client.device(),
                        "session_id": self._client.device_id,
                        "session_key": session_key,
                    },
                },
            },
        )
