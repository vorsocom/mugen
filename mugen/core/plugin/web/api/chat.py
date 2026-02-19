"""Implements web chat endpoints (REST + SSE)."""

import fnmatch
import json
import os
from types import SimpleNamespace
from typing import Any
import uuid

from quart import Response, abort, jsonify, request, send_file

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import global_auth_required
from mugen.core.plugin.web.api.decorator import web_platform_required

_ALLOWED_MESSAGE_TYPES = {"text", "audio", "video", "file", "image"}
_MEDIA_MESSAGE_TYPES = {"audio", "video", "file", "image"}

_DEFAULT_MEDIA_STORAGE_PATH = "data/web_media"
_DEFAULT_MEDIA_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_DEFAULT_MEDIA_ALLOWED_MIMETYPES = [
    "audio/*",
    "video/*",
    "image/*",
    "application/*",
]


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _web_client_provider():
    return di.container.web_client


def _resolve_media_storage_path(config: SimpleNamespace) -> str:
    storage_path = _resolve_config_value(
        config,
        ("web", "media", "storage", "path"),
        _DEFAULT_MEDIA_STORAGE_PATH,
    )
    if os.path.isabs(storage_path):
        return storage_path

    basedir = getattr(config, "basedir", None)
    if isinstance(basedir, str) and basedir != "":
        return os.path.abspath(os.path.join(basedir, storage_path))

    return os.path.abspath(storage_path)


def _resolve_media_max_upload_bytes(
    config: SimpleNamespace,
    web_client: IWebClient,
) -> int:
    provider_limit = getattr(web_client, "media_max_upload_bytes", None)
    try:
        if provider_limit is not None:
            parsed = int(provider_limit)
            if parsed > 0:
                return parsed
    except (TypeError, ValueError):
        ...

    configured = _resolve_config_value(
        config,
        ("web", "media", "max_upload_bytes"),
        _DEFAULT_MEDIA_MAX_UPLOAD_BYTES,
    )
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        parsed = _DEFAULT_MEDIA_MAX_UPLOAD_BYTES

    if parsed <= 0:
        return _DEFAULT_MEDIA_MAX_UPLOAD_BYTES

    return parsed


def _resolve_media_allowed_mimetypes(
    config: SimpleNamespace,
    web_client: IWebClient,
) -> list[str]:
    provider_mimes = getattr(web_client, "media_allowed_mimetypes", None)
    if isinstance(provider_mimes, list):
        normalized = [
            str(item).strip().lower()
            for item in provider_mimes
            if isinstance(item, str) and item.strip() != ""
        ]
        if normalized:
            return normalized

    configured = _resolve_config_value(
        config,
        ("web", "media", "allowed_mimetypes"),
        _DEFAULT_MEDIA_ALLOWED_MIMETYPES,
    )
    if not isinstance(configured, list):
        return list(_DEFAULT_MEDIA_ALLOWED_MIMETYPES)

    normalized = [
        str(item).strip().lower()
        for item in configured
        if isinstance(item, str) and item.strip() != ""
    ]
    if normalized:
        return normalized

    return list(_DEFAULT_MEDIA_ALLOWED_MIMETYPES)


def _resolve_config_value(
    config: SimpleNamespace,
    path: tuple[str, ...],
    default: Any,
) -> Any:
    node: Any = config
    for item in path:
        node = getattr(node, item, None)
        if node is None:
            return default
    return node


def _mimetype_allowed(
    mime_type: str,
    *,
    allowed_mimetypes: list[str],
    web_client: IWebClient,
) -> bool:
    checker = getattr(web_client, "mimetype_allowed", None)
    if callable(checker):
        return bool(checker(mime_type))

    normalized_mime = str(mime_type or "").strip().lower()
    if normalized_mime == "":
        return False

    for allowed in allowed_mimetypes:
        if fnmatch.fnmatch(normalized_mime, allowed):
            return True

    return False


def _remove_file_if_exists(file_path: str | None) -> None:
    if not isinstance(file_path, str) or file_path == "":
        return
    try:
        os.remove(file_path)
    except OSError:
        ...


def _normalize_message_type(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("message_type is required")
    normalized = value.strip().lower()
    if normalized == "":
        raise ValueError("message_type is required")
    if normalized not in _ALLOWED_MESSAGE_TYPES:
        raise ValueError(f"Unsupported message_type: {normalized}")
    return normalized


def _normalize_client_message_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("client_message_id is required")

    normalized = value.strip()
    if normalized == "":
        raise ValueError("client_message_id is required")

    return normalized


def _parse_metadata(value: Any) -> dict[str, Any] | None:
    if value in [None, ""]:
        return None

    if not isinstance(value, str):
        raise ValueError("metadata must be a JSON object string")

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("metadata must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")

    return parsed


@api.post("/core/web/v1/messages")
@web_platform_required
@global_auth_required
async def web_messages_create(  # pylint: disable=too-many-locals
    auth_user: str,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    web_client_provider=_web_client_provider,
):
    """Accept a web chat message and enqueue asynchronous processing."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    web_client: IWebClient = web_client_provider()

    form = await request.form
    files = await request.files

    conversation_id = form.get("conversation_id")
    if not isinstance(conversation_id, str) or conversation_id.strip() == "":
        abort(400, "conversation_id is required")

    try:
        message_type = _normalize_message_type(form.get("message_type"))
    except ValueError as exc:
        abort(400, str(exc))

    try:
        client_message_id = _normalize_client_message_id(form.get("client_message_id"))
    except ValueError as exc:
        abort(400, str(exc))
    text = form.get("text")
    try:
        metadata = _parse_metadata(form.get("metadata"))
    except ValueError as exc:
        abort(400, str(exc))

    if message_type == "text":
        if text is None or str(text).strip() == "":
            abort(400, "text is required for message_type=text")

    uploaded_file = files.get("file")
    if message_type in _MEDIA_MESSAGE_TYPES and uploaded_file is None:
        abort(400, f"file is required for message_type={message_type}")

    if message_type not in _MEDIA_MESSAGE_TYPES and uploaded_file is not None:
        abort(400, f"file is not supported for message_type={message_type}")

    file_path: str | None = None
    mime_type: str | None = None
    original_filename: str | None = None

    if uploaded_file is not None:
        max_upload_bytes = _resolve_media_max_upload_bytes(config, web_client)
        allowed_mimetypes = _resolve_media_allowed_mimetypes(config, web_client)

        mime_type = str(getattr(uploaded_file, "mimetype", "") or "").strip().lower()
        if not _mimetype_allowed(
            mime_type,
            allowed_mimetypes=allowed_mimetypes,
            web_client=web_client,
        ):
            abort(415, "disallowed file mimetype")

        content_length = getattr(uploaded_file, "content_length", None)
        try:
            if content_length is not None and int(content_length) > max_upload_bytes:
                abort(413, "file exceeds max_upload_bytes")
        except (TypeError, ValueError):
            ...

        storage_path = _resolve_media_storage_path(config)
        os.makedirs(storage_path, exist_ok=True)

        original_filename = getattr(uploaded_file, "filename", None)
        extension = ""
        if isinstance(original_filename, str):
            _, raw_extension = os.path.splitext(original_filename)
            if len(raw_extension) <= 16:
                extension = raw_extension

        file_name = f"{uuid.uuid4().hex}{extension}"
        file_path = os.path.join(storage_path, file_name)
        await uploaded_file.save(file_path)

        try:
            actual_size = os.path.getsize(file_path)
        except OSError:
            _remove_file_if_exists(file_path)
            abort(500, "failed to persist upload")

        if actual_size > max_upload_bytes:
            _remove_file_if_exists(file_path)
            abort(413, "file exceeds max_upload_bytes")

    try:
        response_payload = await web_client.enqueue_message(
            auth_user=auth_user,
            conversation_id=conversation_id,
            message_type=message_type,
            text=text,
            metadata=metadata,
            file_path=file_path,
            mime_type=mime_type,
            original_filename=original_filename,
            client_message_id=client_message_id,
        )
    except PermissionError:
        _remove_file_if_exists(file_path)
        abort(403)
    except OverflowError:
        _remove_file_if_exists(file_path)
        abort(429, "web queue is full")
    except ValueError as exc:
        _remove_file_if_exists(file_path)
        abort(400, str(exc))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        _remove_file_if_exists(file_path)
        logger.exception("Failed to enqueue web message: %s", exc)
        abort(500)

    return jsonify(response_payload), 202


@api.get("/core/web/v1/events")
@web_platform_required
@global_auth_required
async def web_events_stream(
    auth_user: str,
    logger_provider=_logger_provider,
    web_client_provider=_web_client_provider,
):
    """Stream web chat events over Server-Sent Events (SSE)."""
    logger: ILoggingGateway = logger_provider()
    web_client: IWebClient = web_client_provider()

    conversation_id = request.args.get("conversation_id")
    if not isinstance(conversation_id, str) or conversation_id.strip() == "":
        abort(400, "conversation_id is required")

    last_event_id = request.headers.get("Last-Event-ID")
    if not isinstance(last_event_id, str) or last_event_id.strip() == "":
        last_event_id = request.args.get("last_event_id")

    try:
        stream = await web_client.stream_events(
            auth_user=auth_user,
            conversation_id=conversation_id,
            last_event_id=last_event_id,
        )
    except PermissionError:
        abort(403)
    except KeyError:
        abort(404)
    except ValueError as exc:
        abort(400, str(exc))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to open web event stream: %s", exc)
        abort(500)

    return Response(
        stream,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api.get("/core/web/v1/media/<token>")
@web_platform_required
@global_auth_required
async def web_media_download(
    token: str,
    auth_user: str,
    web_client_provider=_web_client_provider,
):
    """Resolve and stream media bytes for a valid web download token."""
    web_client: IWebClient = web_client_provider()

    media = await web_client.resolve_media_download(auth_user=auth_user, token=token)
    if not isinstance(media, dict):
        abort(404)

    file_path = media.get("file_path")
    if not isinstance(file_path, str) or file_path == "" or not os.path.exists(file_path):
        abort(404)

    return await send_file(
        file_path,
        mimetype=media.get("mime_type"),
        as_attachment=False,
        attachment_filename=media.get("filename"),
        conditional=False,
    )
