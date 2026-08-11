"""
Provides webhook decorators for the WhatsApp Cloud API (WACAPI) endpoints.
"""

from dataclasses import dataclass, field
from functools import wraps
import hashlib
import hmac
import ipaddress
import json
import os
import time
from types import SimpleNamespace
import uuid


from quart import abort, request
from werkzeug.exceptions import HTTPException

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)
from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeDispatch,
    WhatsAppWebhookChangeEnvelope,
    normalize_webhook_change_field,
    safe_webhook_change_field,
)

_WEBHOOK_METRICS: dict[str, int] = {}


@dataclass(slots=True)  # pylint: disable=too-many-instance-attributes
class WhatsAppWebhookContext:
    """Authenticated and classified WhatsApp webhook request data."""

    request_id: str
    payload_fingerprint: str
    filtered_payload: dict[str, object] = field(default_factory=dict)
    client_profile_id: str | None = None
    object_type: str = "unknown"
    entry_count: int = 0
    change_count: int = 0
    change_fields: tuple[str, ...] = ()
    message_change_count: int = 0
    change_envelopes: tuple[WhatsAppWebhookChangeEnvelope, ...] = ()
    dispatch_results: tuple[WhatsAppWebhookChangeDispatch, ...] = ()
    dispatch_metrics_recorded: bool = False


def _new_webhook_context(raw_body: bytes) -> WhatsAppWebhookContext:
    return WhatsAppWebhookContext(
        request_id=uuid.uuid4().hex,
        payload_fingerprint=hashlib.sha256(raw_body).hexdigest()[:16],
    )


def _safe_client_profile_id(client_profile: object) -> str | None:
    profile_id = str(getattr(client_profile, "id", "")).strip()
    try:
        return str(uuid.UUID(profile_id))
    except ValueError:
        return None


def _safe_change_field(value: object) -> str:
    return safe_webhook_change_field(value)


def _configured_waba_id(runtime_config: object) -> str | None:
    try:
        value = runtime_config.whatsapp.business.waba_id
    except AttributeError:
        return None
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value.strip()


def _increment_webhook_metric(outcome: str, dimension: str) -> None:
    metric_name = f"whatsapp.webhook.{outcome}.{dimension}"
    _WEBHOOK_METRICS[metric_name] = _WEBHOOK_METRICS.get(metric_name, 0) + 1


def webhook_metrics_snapshot() -> dict[str, int]:
    """Return process-local low-cardinality webhook counters."""

    return dict(_WEBHOOK_METRICS)


def _log_webhook_outcome(
    *,
    logger: ILoggingGateway,
    context: WhatsAppWebhookContext,
    level: str,
    outcome: str,
    http_status: int,
    reason_code: str,
    started: float,
) -> None:
    elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
    change_fields = ",".join(context.change_fields) or "none"
    client_profile_id = context.client_profile_id or "unresolved"
    message = (
        "WhatsApp webhook"
        f" request_id={context.request_id}"
        f" payload_fingerprint={context.payload_fingerprint}"
        f" object_type={context.object_type}"
        f" entry_count={context.entry_count}"
        f" change_count={context.change_count}"
        f" change_fields={change_fields}"
        f" outcome={outcome}"
        f" http_status={http_status}"
        f" reason_code={reason_code}"
        f" elapsed_ms={elapsed_ms:.2f}"
        f" client_profile_id={client_profile_id}"
        f" handler_count={sum(item.handler_count for item in context.dispatch_results)}"
        f" handled_count={sum(item.handled_count for item in context.dispatch_results)}"
        f" ignored_count={sum(item.ignored_count for item in context.dispatch_results)}"
        " permanent_failure_count="
        f"{sum(item.permanent_failure_count for item in context.dispatch_results)}"
        " retryable_failure_count="
        f"{sum(item.retryable_failure_count for item in context.dispatch_results)}"
    )
    getattr(logger, level)(message)


def _record_dispatch_metrics(context: WhatsAppWebhookContext) -> None:
    if context.dispatch_metrics_recorded:
        return
    for result in context.dispatch_results:
        if result.handler_count == 0 and result.change_field != "messages":
            _increment_webhook_metric("ignored", result.safe_change_field)
        for _index in range(result.handled_count):
            _increment_webhook_metric("accepted", result.safe_change_field)
        for _index in range(result.ignored_count):
            _increment_webhook_metric("ignored", result.safe_change_field)
        for _index in range(result.permanent_failure_count):
            _increment_webhook_metric("rejected", "permanent_handler_failure")
        for _index in range(result.retryable_failure_count):
            _increment_webhook_metric("rejected", "retryable_handler_failure")
    context.dispatch_metrics_recorded = True


def _dispatch_failure_reason(context: WhatsAppWebhookContext) -> str | None:
    if any(item.retryable_failure_count for item in context.dispatch_results):
        return "retryable_handler_failure"
    if any(item.permanent_failure_count for item in context.dispatch_results):
        return "permanent_handler_failure"
    return None


def _reject_webhook(
    *,
    logger: ILoggingGateway,
    context: WhatsAppWebhookContext,
    started: float,
    http_status: int,
    reason_code: str,
    level: str,
) -> None:
    _increment_webhook_metric("rejected", reason_code)
    _log_webhook_outcome(
        logger=logger,
        context=context,
        level=level,
        outcome="rejected",
        http_status=http_status,
        reason_code=reason_code,
        started=started,
    )
    abort(http_status)


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


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


def _extract_change_phone_number_id(change: dict[str, object]) -> str | None:
    value = change.get("value")
    if not isinstance(value, dict):
        return None
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        return None
    phone_number_id = metadata.get("phone_number_id")
    if isinstance(phone_number_id, str) and phone_number_id.strip() != "":
        return phone_number_id.strip()
    return None


def whatsapp_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Check that the WhatsApp platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "whatsapp" not in config.mugen.platforms:
                    logger.error("WhatsApp platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def whatsapp_request_signature_verification_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()
            data = await request.get_data()
            context = _new_webhook_context(data)
            _increment_webhook_metric("received", "total")

            service = _client_profile_service()
            if service is None:
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=500,
                    reason_code="profile_resolution_failed",
                    level="error",
                )

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=400,
                    reason_code="profile_resolution_failed",
                    level="warning",
                )

            try:
                client_profile = await service.resolve_active_by_identifier(
                    platform_key="whatsapp",
                    identifier_type="path_token",
                    identifier_value=path_token,
                )
            except (KeyError, RuntimeError, TypeError):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=500,
                    reason_code="profile_resolution_failed",
                    level="error",
                )

            if client_profile is None:
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=401,
                    reason_code="profile_resolution_failed",
                    level="warning",
                )

            context.client_profile_id = _safe_client_profile_id(client_profile)

            try:
                runtime_config = await service.build_runtime_config(
                    config=config,
                    client_profile=client_profile,
                )
                app_secret = str(runtime_config.whatsapp.app.secret)
            except (AttributeError, KeyError, RuntimeError, TypeError):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=500,
                    reason_code="profile_resolution_failed",
                    level="error",
                )

            xhubsig = request.headers.get("X-Hub-Signature-256")
            if not isinstance(xhubsig, str) or xhubsig == "":
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=400,
                    reason_code="missing_signature",
                    level="warning",
                )

            hexdigest = hmac.new(
                app_secret.encode("utf8"),
                data,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(xhubsig, f"sha256={hexdigest}"):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=401,
                    reason_code="invalid_signature",
                    level="warning",
                )

            _increment_webhook_metric("authenticated", "total")
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=400,
                    reason_code="malformed_json",
                    level="error",
                )

            if not isinstance(payload, dict):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=400,
                    reason_code="malformed_payload",
                    level="error",
                )

            context.object_type = (
                "whatsapp_business_account"
                if payload.get("object") == "whatsapp_business_account"
                else "unknown"
            )
            entries = payload.get("entry")
            if not isinstance(entries, list):
                _reject_webhook(
                    logger=logger,
                    context=context,
                    started=started,
                    http_status=400,
                    reason_code="malformed_payload",
                    level="error",
                )

            context.entry_count = len(entries)
            expected_phone_number_id = str(
                getattr(client_profile, "phone_number_id", "") or ""
            ).strip()
            expected_waba_id = _configured_waba_id(runtime_config)
            filtered_entries: list[dict[str, object]] = []
            change_fields: set[str] = set()
            change_envelopes: list[WhatsAppWebhookChangeEnvelope] = []

            for entry_index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    _reject_webhook(
                        logger=logger,
                        context=context,
                        started=started,
                        http_status=400,
                        reason_code="malformed_payload",
                        level="error",
                    )
                entry_id = entry.get("id")
                if expected_waba_id is not None and (
                    not isinstance(entry_id, str)
                    or entry_id.strip() != expected_waba_id
                ):
                    _reject_webhook(
                        logger=logger,
                        context=context,
                        started=started,
                        http_status=401,
                        reason_code="waba_id_mismatch",
                        level="warning",
                    )
                changes = entry.get("changes")
                if not isinstance(changes, list):
                    _reject_webhook(
                        logger=logger,
                        context=context,
                        started=started,
                        http_status=400,
                        reason_code="malformed_payload",
                        level="error",
                    )
                filtered_changes: list[dict[str, object]] = []
                for change_index, change in enumerate(changes):
                    if not isinstance(change, dict):
                        _reject_webhook(
                            logger=logger,
                            context=context,
                            started=started,
                            http_status=400,
                            reason_code="malformed_payload",
                            level="error",
                        )
                    context.change_count += 1
                    try:
                        raw_change_field = normalize_webhook_change_field(
                            change.get("field")
                        )
                    except ValueError:
                        _reject_webhook(
                            logger=logger,
                            context=context,
                            started=started,
                            http_status=400,
                            reason_code="malformed_payload",
                            level="error",
                        )
                    change_value = change.get("value")
                    if not isinstance(change_value, dict):
                        _reject_webhook(
                            logger=logger,
                            context=context,
                            started=started,
                            http_status=400,
                            reason_code="malformed_payload",
                            level="error",
                        )
                    safe_change_field = _safe_change_field(raw_change_field)
                    change_fields.add(safe_change_field)
                    context.change_fields = tuple(sorted(change_fields))
                    change_envelopes.append(
                        WhatsAppWebhookChangeEnvelope.build(
                            request_id=context.request_id,
                            payload_fingerprint=context.payload_fingerprint,
                            client_profile_id=context.client_profile_id,
                            object_type=context.object_type,
                            entry_id=entry_id,
                            entry_time=entry.get("time"),
                            entry_index=entry_index,
                            change_index=change_index,
                            change_field=raw_change_field,
                            change_value=change_value,
                        )
                    )
                    if raw_change_field != "messages":
                        continue

                    phone_number_id = _extract_change_phone_number_id(change)
                    if phone_number_id is None:
                        _reject_webhook(
                            logger=logger,
                            context=context,
                            started=started,
                            http_status=400,
                            reason_code="missing_phone_number_id_for_messages",
                            level="error",
                        )
                    if phone_number_id != expected_phone_number_id:
                        _reject_webhook(
                            logger=logger,
                            context=context,
                            started=started,
                            http_status=401,
                            reason_code="phone_number_id_mismatch",
                            level="warning",
                        )
                    filtered_changes.append(change)
                    context.message_change_count += 1

                if filtered_changes:
                    filtered_entry = dict(entry)
                    filtered_entry["changes"] = filtered_changes
                    filtered_entries.append(filtered_entry)

            context.change_fields = tuple(sorted(change_fields))
            context.change_envelopes = tuple(change_envelopes)
            context.filtered_payload = dict(payload)
            context.filtered_payload["entry"] = filtered_entries
            kwargs["whatsapp_webhook_context"] = context

            try:
                result = await func(*args, **kwargs)
            except HTTPException as exc:
                http_status = int(exc.code or 500)
                _record_dispatch_metrics(context)
                reason_code = _dispatch_failure_reason(context) or "routing_failure"
                if reason_code == "routing_failure":
                    _increment_webhook_metric("rejected", reason_code)
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="error",
                    outcome="rejected",
                    http_status=http_status,
                    reason_code=reason_code,
                    started=started,
                )
                raise
            except Exception:  # pylint: disable=broad-exception-caught
                _record_dispatch_metrics(context)
                reason_code = _dispatch_failure_reason(context) or "routing_failure"
                if reason_code == "routing_failure":
                    _increment_webhook_metric("rejected", reason_code)
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="error",
                    outcome="rejected",
                    http_status=500,
                    reason_code=reason_code,
                    started=started,
                )
                raise

            _record_dispatch_metrics(context)
            if context.message_change_count > 0:
                for _index in range(context.message_change_count):
                    _increment_webhook_metric("accepted", "messages")
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="info",
                    outcome="accepted",
                    http_status=200,
                    reason_code="message_event_accepted",
                    started=started,
                )
            elif any(item.permanent_failure_count for item in context.dispatch_results):
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="warning",
                    outcome="acknowledged",
                    http_status=200,
                    reason_code="permanent_handler_failure",
                    started=started,
                )
            elif any(item.handled_count for item in context.dispatch_results):
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="info",
                    outcome="accepted",
                    http_status=200,
                    reason_code="change_handler_handled",
                    started=started,
                )
            else:
                reason_code = (
                    "no_registered_handler"
                    if any(item.handler_count == 0 for item in context.dispatch_results)
                    or not context.dispatch_results
                    else "change_handler_ignored"
                )
                _log_webhook_outcome(
                    logger=logger,
                    context=context,
                    level="info",
                    outcome="ignored",
                    http_status=200,
                    reason_code=reason_code,
                    started=started,
                )

            return result

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def whatsapp_server_ip_allow_list_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                verification_required = config.whatsapp.servers.verify_ip
            except (AttributeError, KeyError):
                logger.error("WhatsApp IP verification configuration missing.")
                abort(500)

            if not isinstance(verification_required, bool):
                logger.error("WhatsApp IP verification configuration invalid.")
                abort(500)

            if verification_required is False:
                return await func(*args, **kwargs)

            try:
                networks: list
                with open(
                    os.path.join(config.basedir, config.whatsapp.servers.allowed),
                    "r",
                    encoding="utf8",
                ) as f:
                    networks = [line.strip() for line in f if line.strip() != ""]
            except (AttributeError, FileNotFoundError, IsADirectoryError, KeyError):
                logger.error("WhatsApp servers allow list not found.")
                abort(500)

            trust_forwarded_for = bool(
                getattr(config.whatsapp.servers, "trust_forwarded_for", False)
            )
            remote_addr = request.remote_addr
            if trust_forwarded_for:
                forwarded_for = request.headers.get("X-Forwarded-For")
                if isinstance(forwarded_for, str) and forwarded_for.strip() != "":
                    remote_addr = forwarded_for.split(",")[0].strip()
            if remote_addr in [None, ""]:
                logger.error("Remote address could not be determined.")
                abort(400)

            try:
                remote_ip = ipaddress.ip_address(remote_addr)
            except ValueError:
                logger.error("Remote address is invalid.")
                abort(400)

            try:
                hits = [
                    network
                    for network in networks
                    if remote_ip in ipaddress.ip_network(network)
                ]
            except ValueError:
                logger.error("Invalid CIDR entry in WhatsApp allow list.")
                abort(500)

            if len(hits) == 0:
                logger.error("Remote address not in allow list.")
                abort(403)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator
