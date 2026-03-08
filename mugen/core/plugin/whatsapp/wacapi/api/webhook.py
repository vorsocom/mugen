"""
Implements webhook endpoints for the WhatsApp Cloud API (WACAPI).
"""

from types import SimpleNamespace

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.ingress import IMessagingIngressService
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.whatsapp.wacapi.api.decorator import (
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)
from mugen.core.service.messaging_ingress_extractors import (
    extract_whatsapp_stage_entries,
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


@api.get("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wacapi_subscription(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Whatsapp Cloud API verification."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()

    if request.args.get("hub.mode") != "subscribe":
        logger.error("hub.mode incorrect.")
        abort(400)

    if request.args.get("hub.verify_token") in [None, ""]:
        logger.error("hub.verify_token not supplied or is empty.")
        abort(400)

    try:
        if (
            request.args.get("hub.verify_token")
            != config.whatsapp.webhook.verification_token
        ):
            logger.error("Incorrect verification token.")
            abort(400)
    except AttributeError:
        logger.error("Could not get verification token.")
        abort(500)

    if request.args.get("hub.challenge") in [None, ""]:
        logger.error("hub.challenge not supplied or is empty.")
        abort(400)

    return request.args.get("hub.challenge")


@api.post("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
@whatsapp_request_signature_verification_required
async def whatsapp_wacapi_event(
    ipc_provider=None,
    ingress_provider=_ingress_provider,
    relational_storage_gateway_provider=_relational_storage_gateway_provider,
    logger_provider=_logger_provider,
):
    """Respond to Whatsapp Cloud API events."""
    # Get request data.
    # get_json was not used to make code more
    # cosistent with signature verification decorator
    # for testing.
    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    ipc_svc: IIPCService | None = ipc_provider() if callable(ipc_provider) else None
    if ipc_svc is not None:
        response = await ipc_svc.handle_ipc_request(
            IPCCommandRequest(
                platform="whatsapp",
                command="whatsapp_wacapi_event",
                data=data,
            )
        )
        if response.errors:
            logger.warning(
                "WhatsApp webhook processed with IPC errors"
                " command=whatsapp_wacapi_event"
                f" error_count={len(response.errors)}"
            )
        return {"response": "OK"}

    ingress_svc: IMessagingIngressService = ingress_provider()
    relational_storage_gateway: IRelationalStorageGateway = (
        relational_storage_gateway_provider()
    )
    try:
        entries = await extract_whatsapp_stage_entries(
            payload=data,
            relational_storage_gateway=relational_storage_gateway,
            logging_gateway=logger,
        )
        await ingress_svc.stage(entries)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "WhatsApp webhook staging failed "
            f"error_type={type(exc).__name__} error={exc}"
        )
        abort(500)
    return {"response": "OK"}
