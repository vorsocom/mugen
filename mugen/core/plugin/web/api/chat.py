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
_STRUCTURED_COMPOSITION_MODES = {
    "message_with_attachments",
    "attachment_with_caption",
}
_STRUCTURED_ATTACHMENT_FILE_KEY_PREFIX = "files["

_DEFAULT_MEDIA_STORAGE_PATH = "data/web_media"
_DEFAULT_MEDIA_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE = 10
_DEFAULT_MEDIA_ALLOWED_MIMETYPES = [
    "audio/*",
    "video/*",
    "image/*",
    "application/*",
]

_STRUCTURED_MIXED_CONTRACT_MESSAGE = "mixed legacy and structured payload fields"
_STRUCTURED_INVALID_EMPTY_MESSAGE = "invalid empty message"
_STRUCTURED_INVALID_CAPTION_TARGET = "invalid caption target"
_STRUCTURED_INVALID_ATTACHMENT_PART = "invalid attachment part"
_STRUCTURED_INVALID_STRUCTURE = "invalid structure"
_STRUCTURED_UNSUPPORTED_MEDIA_TYPE = "unsupported media type"
_STRUCTURED_PAYLOAD_TOO_LARGE = "payload too large"


class _StructuredPayloadError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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


def _resolve_media_max_attachments_per_message(
    config: SimpleNamespace,
    web_client: IWebClient,
) -> int:
    provider_limit = getattr(web_client, "media_max_attachments_per_message", None)
    try:
        if provider_limit is not None:
            parsed = int(provider_limit)
            if parsed > 0:
                return parsed
    except (TypeError, ValueError):
        ...

    configured = _resolve_config_value(
        config,
        ("web", "media", "max_attachments_per_message"),
        _DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE,
    )
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        parsed = _DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE

    if parsed <= 0:
        return _DEFAULT_MEDIA_MAX_ATTACHMENTS_PER_MESSAGE

    return parsed


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


def _remove_files_if_exist(file_paths: list[str]) -> None:
    for file_path in file_paths:
        _remove_file_if_exists(file_path)


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


def _mapping_keys(mapping: Any) -> set[str]:
    if isinstance(mapping, dict):
        return {key for key in mapping if isinstance(key, str)}

    if hasattr(mapping, "keys"):
        return {key for key in mapping.keys() if isinstance(key, str)}

    return set()


def _iter_file_items(files: Any) -> list[tuple[str, Any]]:
    if isinstance(files, dict):
        return [(key, value) for key, value in files.items() if isinstance(key, str)]

    if hasattr(files, "items"):
        try:
            return [
                (key, value)
                for key, value in files.items(multi=True)
                if isinstance(key, str)
            ]
        except TypeError:
            return [(key, value) for key, value in files.items() if isinstance(key, str)]

    return []


def _structured_payload_present(form: Any, files: Any) -> bool:
    form_keys = _mapping_keys(form)
    if "composition_mode" in form_keys or "parts" in form_keys:
        return True

    return any(
        file_key.startswith(_STRUCTURED_ATTACHMENT_FILE_KEY_PREFIX)
        for file_key, _ in _iter_file_items(files)
    )


def _legacy_payload_present(form: Any, files: Any) -> bool:
    form_keys = _mapping_keys(form)
    if "message_type" in form_keys or "text" in form_keys:
        return True

    return any(file_key == "file" for file_key, _ in _iter_file_items(files))


def _normalize_composition_mode(value: Any) -> str:
    if not isinstance(value, str):
        raise _StructuredPayloadError(400, "composition_mode is required")

    normalized = value.strip().lower()
    if normalized == "":
        raise _StructuredPayloadError(400, "composition_mode is required")

    if normalized not in _STRUCTURED_COMPOSITION_MODES:
        raise _StructuredPayloadError(400, "composition_mode is invalid")

    return normalized


def _parse_structured_parts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise _StructuredPayloadError(400, "parts is required")

    raw_parts = value.strip()
    if raw_parts == "":
        raise _StructuredPayloadError(400, "parts is required")

    try:
        parsed = json.loads(raw_parts)
    except json.JSONDecodeError as exc:
        raise _StructuredPayloadError(400, "parts must be valid JSON") from exc

    if not isinstance(parsed, list):
        raise _StructuredPayloadError(400, "parts must be a JSON array")

    normalized_parts: list[dict[str, Any]] = []
    for raw_part in parsed:
        if not isinstance(raw_part, dict):
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        raw_type = raw_part.get("type")
        if not isinstance(raw_type, str):
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        part_type = raw_type.strip().lower()
        if part_type == "text":
            if "caption" in raw_part:
                raise _StructuredPayloadError(400, _STRUCTURED_INVALID_CAPTION_TARGET)

            text = raw_part.get("text")
            if text is None:
                text = ""

            normalized_parts.append({"type": "text", "text": str(text)})
            continue

        if part_type != "attachment":
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        attachment_id = raw_part.get("id")
        if not isinstance(attachment_id, str) or attachment_id.strip() == "":
            raise _StructuredPayloadError(400, _STRUCTURED_INVALID_ATTACHMENT_PART)

        caption = raw_part.get("caption")
        normalized_caption = None
        if caption is not None:
            normalized_caption = str(caption).strip()

        attachment_metadata = raw_part.get("metadata")
        if attachment_metadata is None:
            attachment_metadata = {}
        elif not isinstance(attachment_metadata, dict):
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        normalized_parts.append(
            {
                "type": "attachment",
                "id": attachment_id.strip(),
                "caption": normalized_caption,
                "metadata": dict(attachment_metadata),
            }
        )

    return normalized_parts


def _normalize_structured_uploads(files: Any) -> dict[str, Any]:
    attachment_uploads: dict[str, Any] = {}
    for file_key, upload in _iter_file_items(files):
        if not (
            file_key.startswith(_STRUCTURED_ATTACHMENT_FILE_KEY_PREFIX)
            and file_key.endswith("]")
        ):
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        attachment_id = file_key[len(_STRUCTURED_ATTACHMENT_FILE_KEY_PREFIX) : -1].strip()
        if attachment_id == "":
            raise _StructuredPayloadError(400, _STRUCTURED_INVALID_ATTACHMENT_PART)

        if attachment_id in attachment_uploads:
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

        attachment_uploads[attachment_id] = upload

    return attachment_uploads


def _infer_upload_extension(original_filename: Any) -> str:
    extension = ""
    if isinstance(original_filename, str):
        _, raw_extension = os.path.splitext(original_filename)
        if len(raw_extension) <= 16:
            extension = raw_extension
    return extension


async def _persist_structured_upload(
    *,
    uploaded_file: Any,
    config: SimpleNamespace,
    web_client: IWebClient,
    max_upload_bytes: int,
    allowed_mimetypes: list[str],
) -> dict[str, Any]:
    mime_type = str(getattr(uploaded_file, "mimetype", "") or "").strip().lower()
    if not _mimetype_allowed(
        mime_type,
        allowed_mimetypes=allowed_mimetypes,
        web_client=web_client,
    ):
        raise _StructuredPayloadError(415, _STRUCTURED_UNSUPPORTED_MEDIA_TYPE)

    content_length = getattr(uploaded_file, "content_length", None)
    try:
        if content_length is not None and int(content_length) > max_upload_bytes:
            raise _StructuredPayloadError(413, _STRUCTURED_PAYLOAD_TOO_LARGE)
    except (TypeError, ValueError):
        ...

    storage_path = _resolve_media_storage_path(config)
    os.makedirs(storage_path, exist_ok=True)

    original_filename = getattr(uploaded_file, "filename", None)
    extension = _infer_upload_extension(original_filename)
    file_path = os.path.join(storage_path, f"{uuid.uuid4().hex}{extension}")
    await uploaded_file.save(file_path)

    try:
        actual_size = os.path.getsize(file_path)
    except OSError as exc:
        _remove_file_if_exists(file_path)
        raise _StructuredPayloadError(500, "failed to persist upload") from exc

    if actual_size > max_upload_bytes:
        _remove_file_if_exists(file_path)
        raise _StructuredPayloadError(413, _STRUCTURED_PAYLOAD_TOO_LARGE)

    return {
        "file_path": file_path,
        "mime_type": mime_type,
        "original_filename": original_filename,
    }


# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
async def _build_structured_message_metadata(
    *,
    form: Any,
    files: Any,
    config: SimpleNamespace,
    web_client: IWebClient,
    metadata: dict[str, Any] | None,
    persisted_file_paths: list[str],
) -> dict[str, Any]:
    composition_mode = _normalize_composition_mode(form.get("composition_mode"))
    parts = _parse_structured_parts(form.get("parts"))

    max_attachments_per_message = _resolve_media_max_attachments_per_message(
        config,
        web_client,
    )
    max_upload_bytes = _resolve_media_max_upload_bytes(config, web_client)
    allowed_mimetypes = _resolve_media_allowed_mimetypes(config, web_client)

    text_parts = [
        part
        for part in parts
        if part.get("type") == "text" and str(part.get("text", "")).strip() != ""
    ]
    attachment_parts = [part for part in parts if part.get("type") == "attachment"]

    if composition_mode == "attachment_with_caption" and not attachment_parts:
        raise _StructuredPayloadError(400, _STRUCTURED_INVALID_CAPTION_TARGET)

    if not text_parts and not attachment_parts:
        raise _StructuredPayloadError(400, _STRUCTURED_INVALID_EMPTY_MESSAGE)

    if len(attachment_parts) > max_attachments_per_message:
        raise _StructuredPayloadError(413, _STRUCTURED_PAYLOAD_TOO_LARGE)

    if composition_mode == "attachment_with_caption":
        if any(part.get("type") == "text" for part in parts):
            raise _StructuredPayloadError(400, _STRUCTURED_INVALID_CAPTION_TARGET)

    attachment_ids: set[str] = set()
    for part in attachment_parts:
        attachment_id = str(part["id"])
        if attachment_id in attachment_ids:
            raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)
        attachment_ids.add(attachment_id)

        if (
            composition_mode == "attachment_with_caption"
            and str(part.get("caption") or "").strip() == ""
        ):
            raise _StructuredPayloadError(400, _STRUCTURED_INVALID_CAPTION_TARGET)

    attachment_uploads = _normalize_structured_uploads(files)

    orphan_uploads = [upload_id for upload_id in attachment_uploads if upload_id not in attachment_ids]
    if orphan_uploads:
        raise _StructuredPayloadError(422, _STRUCTURED_INVALID_STRUCTURE)

    attachments_by_id: dict[str, dict[str, Any]] = {}
    normalized_attachments: list[dict[str, Any]] = []
    for part in attachment_parts:
        attachment_id = str(part["id"])
        if attachment_id not in attachment_uploads:
            raise _StructuredPayloadError(400, _STRUCTURED_INVALID_ATTACHMENT_PART)

        upload_payload = await _persist_structured_upload(
            uploaded_file=attachment_uploads[attachment_id],
            config=config,
            web_client=web_client,
            max_upload_bytes=max_upload_bytes,
            allowed_mimetypes=allowed_mimetypes,
        )
        persisted_file_paths.append(upload_payload["file_path"])

        attachment_entry = {
            "id": attachment_id,
            "caption": part.get("caption"),
            "metadata": dict(part.get("metadata") or {}),
            "file_path": upload_payload["file_path"],
            "mime_type": upload_payload["mime_type"],
            "original_filename": upload_payload["original_filename"],
        }
        attachments_by_id[attachment_id] = attachment_entry
        normalized_attachments.append(dict(attachment_entry))

    normalized_parts: list[dict[str, Any]] = []
    for part in parts:
        if part.get("type") == "text":
            normalized_parts.append(
                {
                    "type": "text",
                    "text": str(part.get("text", "")),
                }
            )
            continue

        attachment_id = str(part.get("id"))
        attachment_entry = attachments_by_id[attachment_id]

        normalized_parts.append(
            {
                "type": "attachment",
                "id": attachment_id,
                "caption": attachment_entry.get("caption"),
                "metadata": dict(attachment_entry.get("metadata") or {}),
                "mime_type": attachment_entry.get("mime_type"),
                "original_filename": attachment_entry.get("original_filename"),
            }
        )

    structured_metadata = {
        "composition_mode": composition_mode,
        "parts": normalized_parts,
        "attachments": normalized_attachments,
    }
    if metadata is not None:
        structured_metadata["metadata"] = metadata

    return structured_metadata


@api.post("/core/web/v1/messages")
@web_platform_required
@global_auth_required
async def web_messages_create(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
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
        client_message_id = _normalize_client_message_id(form.get("client_message_id"))
    except ValueError as exc:
        abort(400, str(exc))

    try:
        metadata = _parse_metadata(form.get("metadata"))
    except ValueError as exc:
        abort(400, str(exc))

    has_structured_payload = _structured_payload_present(form, files)
    has_legacy_payload = _legacy_payload_present(form, files)

    if has_legacy_payload and has_structured_payload:
        abort(400, _STRUCTURED_MIXED_CONTRACT_MESSAGE)

    persisted_file_paths: list[str] = []

    if has_structured_payload:
        try:
            structured_metadata = await _build_structured_message_metadata(
                form=form,
                files=files,
                config=config,
                web_client=web_client,
                metadata=metadata,
                persisted_file_paths=persisted_file_paths,
            )
            response_payload = await web_client.enqueue_message(
                auth_user=auth_user,
                conversation_id=conversation_id,
                message_type="composed",
                metadata=structured_metadata,
                client_message_id=client_message_id,
            )
        except _StructuredPayloadError as exc:
            _remove_files_if_exist(persisted_file_paths)
            abort(exc.status_code, exc.message)
        except PermissionError:
            _remove_files_if_exist(persisted_file_paths)
            abort(403)
        except OverflowError:
            _remove_files_if_exist(persisted_file_paths)
            abort(429, "web queue is full")
        except ValueError as exc:
            _remove_files_if_exist(persisted_file_paths)
            abort(400, str(exc))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _remove_files_if_exist(persisted_file_paths)
            logger.exception("Failed to enqueue web message: %s", exc)
            abort(500)

        return jsonify(response_payload), 202

    try:
        message_type = _normalize_message_type(form.get("message_type"))
    except ValueError as exc:
        abort(400, str(exc))

    text = form.get("text")
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
