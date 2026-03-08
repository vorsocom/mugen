"""Implements webhook endpoints for the Telegram Bot API."""

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.ingress import IMessagingIngressService
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.telegram.botapi.api.decorator import (
    telegram_platform_required,
    telegram_webhook_path_token_required,
    telegram_webhook_secret_required,
)
from mugen.core.service.messaging_ingress_extractors import (
    extract_telegram_stage_entries,
)


def _config_provider():
    return di.container.config


def _ingress_provider():
    return di.container.ingress_service


def _ipc_provider():
    return di.container.ipc_service


def _relational_storage_gateway_provider():
    return di.container.relational_storage_gateway


def _logger_provider():
    return di.container.logging_gateway


@api.post("/telegram/botapi/webhook/<path_token>")
@telegram_platform_required
@telegram_webhook_path_token_required
@telegram_webhook_secret_required
async def telegram_botapi_webhook_event(
    path_token: str,
    ipc_provider=None,
    ingress_provider=_ingress_provider,
    relational_storage_gateway_provider=_relational_storage_gateway_provider,
    logger_provider=_logger_provider,
):
    """Respond to Telegram Bot API webhook events."""

    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    ipc_svc: IIPCService | None = ipc_provider() if callable(ipc_provider) else None
    if ipc_svc is not None:
        response = await ipc_svc.handle_ipc_request(
            IPCCommandRequest(
                platform="telegram",
                command="telegram_botapi_update",
                data={
                    "path_token": path_token,
                    "payload": data,
                },
            )
        )
        if response.errors:
            logger.warning(
                "Telegram webhook processed with IPC errors"
                " command=telegram_botapi_update"
                f" error_count={len(response.errors)}"
            )
        return {"response": "OK"}

    ingress_svc: IMessagingIngressService = ingress_provider()
    relational_storage_gateway: IRelationalStorageGateway = (
        relational_storage_gateway_provider()
    )
    try:
        entries = await extract_telegram_stage_entries(
            path_token=path_token,
            payload=data,
            relational_storage_gateway=relational_storage_gateway,
            logging_gateway=logger,
        )
        await ingress_svc.stage(entries)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Telegram webhook staging failed "
            f"error_type={type(exc).__name__} error={exc}"
        )
        abort(500)
    return {"response": "OK"}
