"""
Implements webhook endpoints for the WhatsApp Cloud API (WACAPI).
"""

from types import SimpleNamespace
import uuid

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.ingress import IMessagingIngressService
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)
from mugen.core.plugin.whatsapp.wacapi.api.decorator import (
    WhatsAppWebhookContext,
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)
from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeDispatch,
    WhatsAppWebhookChangeEnvelope,
    WhatsAppWebhookChangeRegistry,
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


def _change_registry_provider():
    return di.container.get_ext_service(
        di.EXT_SERVICE_WHATSAPP_WEBHOOK_CHANGE_REGISTRY,
        None,
    )


def _client_profile_service() -> MessagingClientProfileService | None:
    relational_storage_gateway = getattr(
        di.container,
        "relational_storage_gateway",
        None,
    )
    if relational_storage_gateway is None:
        return None
    return MessagingClientProfileService(
        table="admin_messaging_client_profile",
        rsg=relational_storage_gateway,
    )


def _log_change_dispatch(
    *,
    logger: ILoggingGateway,
    envelope: WhatsAppWebhookChangeEnvelope,
    result: WhatsAppWebhookChangeDispatch,
) -> None:
    level = (
        "error"
        if result.retryable_failure_count
        else "warning" if result.permanent_failure_count else "info"
    )
    getattr(logger, level)(
        "WhatsApp webhook change dispatch"
        f" request_id={envelope.request_id}"
        f" payload_fingerprint={envelope.payload_fingerprint}"
        f" client_profile_id={envelope.client_profile_id or 'unresolved'}"
        f" object_type={envelope.object_type}"
        f" entry_index={envelope.entry_index}"
        f" change_index={envelope.change_index}"
        f" change_field={result.safe_change_field}"
        f" event_type={result.event_type}"
        f" handler_count={result.handler_count}"
        f" handled_count={result.handled_count}"
        f" ignored_count={result.ignored_count}"
        f" permanent_failure_count={result.permanent_failure_count}"
        f" retryable_failure_count={result.retryable_failure_count}"
        f" reason_code={result.reason_code}"
    )


async def _dispatch_authenticated_changes(
    *,
    context: WhatsAppWebhookContext,
    logger: ILoggingGateway,
    registry_provider,
) -> bool:
    registry = registry_provider() if callable(registry_provider) else None
    if registry is None:
        registry = WhatsAppWebhookChangeRegistry()

    results: list[WhatsAppWebhookChangeDispatch] = []
    for envelope in context.change_envelopes:
        result = await registry.dispatch(envelope)
        results.append(result)
        if result.handler_count or envelope.change_field != "messages":
            _log_change_dispatch(
                logger=logger,
                envelope=envelope,
                result=result,
            )
    context.dispatch_results = tuple(results)
    return any(result.retryable_failure_count for result in results)


@api.get("/whatsapp/wacapi/webhook/<path_token>")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wacapi_subscription(
    path_token: str,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    client_profile_service_provider=None,
):
    """Whatsapp Cloud API verification."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    if client_profile_service_provider is None:
        client_profile_service_provider = _client_profile_service

    if request.args.get("hub.mode") != "subscribe":
        logger.error("hub.mode incorrect.")
        abort(400)

    if request.args.get("hub.verify_token") in [None, ""]:
        logger.error("hub.verify_token not supplied or is empty.")
        abort(400)

    service = (
        client_profile_service_provider()
        if callable(client_profile_service_provider)
        else None
    )
    if service is None:
        logger.error("Could not get verification token.")
        abort(500)

    try:
        client_profile = await service.resolve_active_by_identifier(
            platform_key="whatsapp",
            identifier_type="path_token",
            identifier_value=path_token,
        )
        if client_profile is None:
            logger.error("Incorrect verification token.")
            abort(401)
        runtime_config = await service.build_runtime_config(
            config=config,
            client_profile=client_profile,
        )
        if request.args.get("hub.verify_token") != str(
            runtime_config.whatsapp.webhook.verification_token
        ):
            logger.error("Incorrect verification token.")
            abort(400)
    except (AttributeError, KeyError, RuntimeError, TypeError):
        logger.error("Could not get verification token.")
        abort(500)

    if request.args.get("hub.challenge") in [None, ""]:
        logger.error("hub.challenge not supplied or is empty.")
        abort(400)

    return request.args.get("hub.challenge")


@api.post("/whatsapp/wacapi/webhook/<path_token>")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
@whatsapp_request_signature_verification_required
async def whatsapp_wacapi_event(
    path_token: str,
    ipc_provider=None,
    ingress_provider=_ingress_provider,
    relational_storage_gateway_provider=_relational_storage_gateway_provider,
    logger_provider=_logger_provider,
    change_registry_provider=_change_registry_provider,
    whatsapp_webhook_context: WhatsAppWebhookContext | None = None,
):
    """Respond to Whatsapp Cloud API events."""
    logger: ILoggingGateway = logger_provider()
    if whatsapp_webhook_context is None:
        logger.error("WhatsApp webhook authenticated context missing.")
        abort(500)

    retry_required = await _dispatch_authenticated_changes(
        context=whatsapp_webhook_context,
        logger=logger,
        registry_provider=change_registry_provider,
    )
    data = whatsapp_webhook_context.filtered_payload
    if whatsapp_webhook_context.message_change_count == 0:
        if retry_required:
            abort(500)
        return {"response": "OK"}

    ipc_svc: IIPCService | None = ipc_provider() if callable(ipc_provider) else None
    if ipc_svc is not None:
        response = await ipc_svc.handle_ipc_request(
            IPCCommandRequest(
                platform="whatsapp",
                command="whatsapp_wacapi_event",
                data={
                    "path_token": path_token,
                    "payload": data,
                    "authenticated_client_profile_id": (
                        whatsapp_webhook_context.client_profile_id
                    ),
                },
            )
        )
        if response.errors:
            logger.warning(
                "WhatsApp webhook processed with IPC errors"
                " command=whatsapp_wacapi_event"
                f" request_id={whatsapp_webhook_context.request_id}"
                " reason_code=routing_failure"
                f" error_count={len(response.errors)}"
            )
        if response.errors or retry_required:
            abort(500)
        return {"response": "OK"}

    ingress_svc: IMessagingIngressService = ingress_provider()
    relational_storage_gateway: IRelationalStorageGateway = (
        relational_storage_gateway_provider()
    )
    try:
        entries = await extract_whatsapp_stage_entries(
            path_token=path_token,
            payload=data,
            relational_storage_gateway=relational_storage_gateway,
            logging_gateway=logger,
            authenticated_client_profile_id=uuid.UUID(
                whatsapp_webhook_context.client_profile_id
            ),
        )
        await ingress_svc.stage(entries)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "WhatsApp webhook staging failed"
            f" reason_code=routing_failure error_type={type(exc).__name__}"
        )
        abort(500)
    if retry_required:
        abort(500)
    return {"response": "OK"}
