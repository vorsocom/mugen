"""Provides an implementation of IIPCExtension to manage devices."""

__all__ = ["DeviceManagementIPCExtension"]

import textwrap
from types import SimpleNamespace

from mugen.core import di
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult


def _config_provider():
    return di.container.config


def _matrix_client_provider():
    return di.container.matrix_client


def _logging_gateway_provider():
    return di.container.logging_gateway


class DeviceManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage devices."""

    def __init__(
        self,
        config: SimpleNamespace | None = None,
        matrix_client: IMatrixClient | None = None,
        logging_gateway: ILoggingGateway | None = None,
    ) -> None:
        self._client = (
            matrix_client
            if matrix_client is not None
            else _matrix_client_provider()
        )
        self._config = config if config is not None else _config_provider()
        self._logging_gateway = (
            logging_gateway
            if logging_gateway is not None
            else _logging_gateway_provider()
        )

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "matrix_get_device_verification_data",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["matrix"]

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "DeviceManagementIPCExtension: Executing command:"
            f" {request.command}"
        )
        match request.command:
            case "matrix_get_device_verification_data":
                response = self._get_device_verification_data()
                return IPCHandlerResult(
                    handler=handler_name,
                    response=response,
                )
            case _:
                return IPCHandlerResult(
                    handler=handler_name,
                    ok=False,
                    code="not_found",
                    error="Unsupported IPC command.",
                )

    def _get_device_verification_data(self) -> dict:
        """Get the assistant device's verification data."""
        session_key = self._resolve_session_key()
        public_name = getattr(
            getattr(getattr(self._config, "matrix", SimpleNamespace()), "client", None),
            "device",
            "",
        )
        session_id = getattr(self._client, "device_id", "")
        return {
            "response": {
                "data": {
                    "public_name": str(public_name),
                    "session_id": str(session_id),
                    "session_key": session_key,
                },
            },
        }

    def _resolve_session_key(self) -> str:
        identity_keys = getattr(
            getattr(getattr(self._client, "olm", None), "account", None),
            "identity_keys",
            None,
        )
        if not isinstance(identity_keys, dict):
            return ""
        raw_key = identity_keys.get("ed25519")
        if not isinstance(raw_key, str) or raw_key == "":
            return ""
        return " ".join(textwrap.wrap(raw_key, 4))
