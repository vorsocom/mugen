"""IPC extension that bridges durable Matrix ingress rows back into the client."""

__all__ = ["MatrixIngressIPCExtension"]

from mugen.core import di
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult


def _matrix_client_provider():
    return di.container.matrix_client


def _logging_gateway_provider():
    return di.container.logging_gateway


class MatrixIngressIPCExtension(IIPCExtension):
    """Durable ingress consumer for Matrix sync-derived events."""

    def __init__(
        self,
        matrix_client: IMatrixClient | None = None,
        logging_gateway: ILoggingGateway | None = None,
    ) -> None:
        self._client = matrix_client if matrix_client is not None else _matrix_client_provider()
        self._logging_gateway = (
            logging_gateway if logging_gateway is not None else _logging_gateway_provider()
        )

    @property
    def ipc_commands(self) -> list[str]:
        return ["matrix_ingress_event"]

    @property
    def platforms(self) -> list[str]:
        return ["matrix"]

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        match request.command:
            case "matrix_ingress_event":
                await self._client.process_ingress_event(request.data)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case _:
                return IPCHandlerResult(
                    handler=handler_name,
                    ok=False,
                    code="not_found",
                    error="Unsupported IPC command.",
                )
