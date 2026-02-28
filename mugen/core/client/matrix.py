"""Provides an implementation of IMatrixClient."""

__all__ = ["DefaultMatrixClient"]

from io import BytesIO

import asyncio
import base64
import hashlib
import inspect
import json
import mimetypes
import os
import tempfile
import traceback
from types import SimpleNamespace
from typing import Coroutine

import aiofiles
from cryptography.fernet import Fernet, InvalidToken

from nio import (
    Api,
    InviteAliasEvent,
    InviteMemberEvent,
    InviteNameEvent,
    KeyVerificationEvent,
    LocalProtocolError,
    LoginResponse,
    MatrixInvitedRoom,
    MatrixRoom,
    MegolmEvent,
    ProfileGetResponse,
    RoomCreateEvent,
    RoomKeyEvent,
    RoomKeyRequest,
    RoomMessage,
    RoomEncryptedAudio,
    RoomEncryptedFile,
    RoomEncryptedImage,
    RoomEncryptedVideo,
    RoomMessageText,
    RoomMemberEvent,
    SendRetryError,
    SyncResponse,
    TagEvent,
)

import nio.crypto
from nio.exceptions import OlmUnverifiedDeviceError
from nio.responses import (
    DirectRoomsResponse,
    DiskDownloadResponse,
    EmptyResponse,
    UploadResponse,
)

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core.utility.platforms import normalize_platforms
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


class DefaultMatrixClient(  # pylint: disable=too-many-instance-attributes
    IMatrixClient
):
    """A custom implementation of IMatrixClient."""

    _default_media_allowed_mimetypes: list[str] = [
        "audio/*",
        "image/*",
        "video/*",
        "application/*",
        "text/*",
    ]

    _default_media_max_download_bytes: int = 20 * 1024 * 1024

    _callback_skip_reason_dm_scope: str = "unsupported_dm_scope"

    _device_trust_mode_allowlist: str = "allowlist"

    _device_trust_mode_permissive: str = "permissive"

    _device_trust_mode_strict_known: str = "strict_known"

    _direct_rooms_event_type: str = "m.direct"

    _legacy_direct_flags_key: str = "m.agent_flags"

    _ipc_callback: Coroutine

    _known_devices_list_key: str = "known_devices_list"

    _matrix_event_hook_command: str = "matrix_event"

    _matrix_event_hook_payload_version: int = 1

    _default_matrix_ipc_queue_size: int = 256
    _default_matrix_ipc_enqueue_timeout_seconds: float = 2.0

    _sync_key: str = "matrix_client_sync_next_batch"
    _encrypted_secret_prefix: str = "enc:v1:"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ):
        self._config = config
        super().__init__(
            homeserver=self._config.matrix.homeserver,
            user=self._config.matrix.client.user,
            store_path=os.path.join(
                self._config.basedir,
                self._config.matrix.storage.olm.path,
            ),
        )
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service
        self._direct_room_ids: set[str] = set()
        self._matrix_ipc_queue_size = self._resolve_matrix_ipc_queue_size()
        self._matrix_ipc_enqueue_timeout_seconds = (
            self._resolve_matrix_ipc_enqueue_timeout_seconds()
        )
        self._matrix_ipc_queue: asyncio.Queue | None = None
        self._matrix_ipc_worker_task: asyncio.Task | None = None
        self._matrix_ipc_worker_stop = asyncio.Event()
        self._sync_token: str | None = None
        self._secret_cipher: Fernet | None = self._build_secret_cipher()

        if self._matrix_secrets_encryption_required() and self._secret_cipher is None:
            raise RuntimeError(
                "Matrix secret encryption key is required in production. "
                "Set security.secrets.encryption_key."
            )

        ## Callbacks
        # Invite Room Events.
        self.add_event_callback(self._cb_invite_alias_event, InviteAliasEvent)
        self.add_event_callback(self._cb_invite_member_event, InviteMemberEvent)
        self.add_event_callback(self._cb_invite_name_event, InviteNameEvent)

        # Room Events.
        self.add_event_callback(self._cb_megolm_event, MegolmEvent)
        self.add_event_callback(self._cb_room_create_event, RoomCreateEvent)
        self.add_event_callback(self._cb_room_member_event, RoomMemberEvent)
        self.add_event_callback(self._cb_room_message, RoomMessage)

        # To-device Events.
        self.add_to_device_callback(
            self._cb_key_verification_event, KeyVerificationEvent
        )
        self.add_to_device_callback(self._cb_room_key_event, RoomKeyEvent)
        self.add_to_device_callback(self._cb_room_key_request, RoomKeyRequest)

        # Responses.
        self.add_response_callback(self._cb_sync_response, SyncResponse)

    async def __aenter__(self) -> "DefaultMatrixClient":
        """Initialisation."""
        self._logging_gateway.debug("DefaultMatrixClient.__aenter__")
        self._start_matrix_ipc_worker()
        stored_access_token = await self._keyval_storage_gateway.get_text(
            "client_access_token"
        )
        stored_access_token = self._decode_secret_value(
            stored_access_token,
            field_name="client_access_token",
        )
        if stored_access_token is None:
            # Load password and device name from storage.
            pw = self._config.matrix.client.password
            dn = self._config.matrix.client.device

            # Attempt  password login.
            resp = await self.login(pw, dn)

            # check login successful
            if isinstance(resp, LoginResponse):
                self._logging_gateway.debug("Password login successful.")
                self._logging_gateway.debug("Saving credentials.")

                # Save credentials.
                await self._keyval_storage_gateway.put_text(
                    "client_access_token",
                    self._encode_secret_value(
                        resp.access_token,
                        field_name="client_access_token",
                    ),
                )
                await self._keyval_storage_gateway.put_text(
                    "client_device_id",
                    self._encode_secret_value(
                        resp.device_id,
                        field_name="client_device_id",
                    ),
                )
                await self._keyval_storage_gateway.put_text(
                    "client_user_id",
                    self._encode_secret_value(
                        resp.user_id,
                        field_name="client_user_id",
                    ),
                )
                self.access_token = resp.access_token
                self.device_id = resp.device_id
                self.user_id = resp.user_id
                self.load_store()
                self._sync_token = await self._keyval_storage_gateway.get_text(
                    self._sync_key
                )
                return self
            else:
                self._logging_gateway.error("Password login failed.")
                raise RuntimeError("Matrix password login failed.")

        # Otherwise the config file exists, so we'll use the stored credentials.
        self._logging_gateway.debug("Login using saved credentials.")
        # open the file in read-only mode.
        self.access_token = stored_access_token
        self.device_id = self._decode_secret_value(
            await self._keyval_storage_gateway.get_text("client_device_id"),
            field_name="client_device_id",
        )
        self.user_id = self._decode_secret_value(
            await self._keyval_storage_gateway.get_text("client_user_id"),
            field_name="client_user_id",
        )
        self._sync_token = await self._keyval_storage_gateway.get_text(self._sync_key)
        self.load_store()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Finalisation."""
        self._logging_gateway.debug("DefaultMatrixClient.__aexit__")
        await self._stop_matrix_ipc_worker()
        try:
            await self.client_session.close()
        except AttributeError:
            ...

    def _matrix_secrets_encryption_required(self) -> bool:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
        ).strip().lower()
        platforms = normalize_platforms(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "platforms", [])
        )
        return environment == "production" and "matrix" in platforms

    def _build_secret_cipher(self) -> Fernet | None:
        security_cfg = getattr(getattr(self._config, "security", SimpleNamespace()), "secrets", None)
        raw_key = getattr(security_cfg, "encryption_key", None)
        if not isinstance(raw_key, str) or raw_key.strip() == "":
            return None

        # Derive stable Fernet key from operator-provided secret material.
        digest = hashlib.sha256(raw_key.strip().encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _encode_secret_value(self, value: str, *, field_name: str) -> str:
        cipher = getattr(self, "_secret_cipher", None)
        if cipher is None:
            return value
        if not isinstance(value, str):
            raise RuntimeError(f"Expected string value for {field_name}.")
        encrypted = cipher.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{self._encrypted_secret_prefix}{encrypted}"

    def _decode_secret_value(self, value: str | None, *, field_name: str) -> str | None:
        if value in [None, ""]:
            return None
        if not isinstance(value, str):
            return None

        if value.startswith(self._encrypted_secret_prefix) is not True:
            return value
        cipher = getattr(self, "_secret_cipher", None)
        if cipher is None:
            raise RuntimeError(
                f"Encrypted value for {field_name} found but no encryption key is configured."
            )

        encrypted_payload = value[len(self._encrypted_secret_prefix) :]
        try:
            decoded = cipher.decrypt(encrypted_payload.encode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError(
                f"Encrypted value for {field_name} could not be decrypted."
            ) from exc
        return decoded.decode("utf-8")

    def _log_send_failure(self, message: str) -> None:
        self._logging_gateway.warning(f"{message}\n{traceback.format_exc()}")

    def _resolve_matrix_ipc_queue_size(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "matrix", SimpleNamespace()), "ipc", None),
            "queue_size",
            self._default_matrix_ipc_queue_size,
        )
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = self._default_matrix_ipc_queue_size
        if parsed <= 0:
            return self._default_matrix_ipc_queue_size
        return parsed

    def _resolve_matrix_ipc_enqueue_timeout_seconds(self) -> float:
        raw_value = getattr(
            getattr(getattr(self._config, "matrix", SimpleNamespace()), "ipc", None),
            "enqueue_timeout_seconds",
            self._default_matrix_ipc_enqueue_timeout_seconds,
        )
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError):
            return self._default_matrix_ipc_enqueue_timeout_seconds

        if parsed <= 0:
            return self._default_matrix_ipc_enqueue_timeout_seconds
        return parsed

    def _start_matrix_ipc_worker(self) -> None:
        if self._ipc_service is None:
            return
        if self._matrix_ipc_worker_task is not None and not self._matrix_ipc_worker_task.done():
            return
        self._matrix_ipc_worker_stop.clear()
        self._matrix_ipc_queue = asyncio.Queue(maxsize=self._matrix_ipc_queue_size)
        self._matrix_ipc_worker_task = asyncio.create_task(
            self._matrix_ipc_worker_loop(),
            name="mugen.matrix.ipc.worker",
        )

    async def _stop_matrix_ipc_worker(self) -> None:
        self._matrix_ipc_worker_stop.set()
        task = self._matrix_ipc_worker_task
        self._matrix_ipc_worker_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                ...
        self._matrix_ipc_queue = None

    async def _dispatch_matrix_ipc_request(
        self,
        request_payload: IPCCommandRequest,
    ) -> None:
        if self._ipc_service is None:
            return
        handle_ipc_request = getattr(self._ipc_service, "handle_ipc_request", None)
        if not callable(handle_ipc_request):
            return
        maybe_dispatch = handle_ipc_request(request_payload)
        if inspect.isawaitable(maybe_dispatch):
            await maybe_dispatch

    async def _matrix_ipc_worker_loop(self) -> None:
        while self._matrix_ipc_worker_stop.is_set() is not True:
            queue = self._matrix_ipc_queue
            if queue is None:
                await asyncio.sleep(0.05)
                continue
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            try:
                await self._dispatch_matrix_ipc_request(payload)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Matrix event extension dispatch failed."
                    f" error={type(exc).__name__}: {exc}"
                )

    @property
    def sync_token(self) -> str:
        """Get the key to access the sync key from persistent storage."""
        return "" if self._sync_token is None else self._sync_token

    async def _load_known_devices(self) -> dict[str, list[str]]:
        payload = await self._keyval_storage_gateway.get_text(self._known_devices_list_key)
        if payload is None:
            return {}

        try:
            loaded = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            self._logging_gateway.warning("Invalid known devices payload; resetting.")
            return {}

        if not isinstance(loaded, dict):
            self._logging_gateway.warning(
                "Known devices payload type mismatch; resetting."
            )
            return {}

        known_devices: dict[str, list[str]] = {}
        for user_id, devices in loaded.items():
            if not isinstance(devices, list):
                continue
            known_devices[user_id] = [str(device_id) for device_id in devices]
        return known_devices

    async def _save_known_devices(self, known_devices: dict[str, list[str]]) -> None:
        await self._keyval_storage_gateway.put_json(
            self._known_devices_list_key,
            known_devices,
        )

    async def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""
        self._logging_gateway.debug("Cleaning up known user devices.")
        known_devices = await self._load_known_devices()
        if not known_devices:
            return

        for user_id in known_devices.keys():
            active_devices = [
                x.device_id for x in self.device_store.active_user_devices(user_id)
            ]
            self._logging_gateway.debug(f"Active devices: {active_devices}")
            known_devices[user_id] = active_devices

        # Persist changes.
        await self._save_known_devices(known_devices)

    async def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""
        self._logging_gateway.debug("Trusting all known user devices.")
        known_devices = await self._load_known_devices()
        for user_id in known_devices.keys():
            self._logging_gateway.debug(f"User: {user_id}")
            for device_id, olm_device in self.device_store[user_id].items():
                if device_id in known_devices[user_id]:
                    # Verify the device.
                    self._logging_gateway.debug(f"Trusting {device_id}.")
                    self.verify_device(olm_device)

    def _resolve_device_trust_mode(self) -> str:
        mode = getattr(
            getattr(
                getattr(
                    getattr(self._config, "matrix", SimpleNamespace()),
                    "security",
                    SimpleNamespace(),
                ),
                "device_trust",
                SimpleNamespace(),
            ),
            "mode",
            self._device_trust_mode_strict_known,
        )
        if not isinstance(mode, str):
            self._logging_gateway.warning(
                "Matrix device trust mode invalid; using strict_known."
            )
            return self._device_trust_mode_strict_known

        mode = mode.strip().lower()
        supported_modes = {
            self._device_trust_mode_strict_known,
            self._device_trust_mode_allowlist,
            self._device_trust_mode_permissive,
        }
        if mode in supported_modes:
            return mode

        self._logging_gateway.warning(
            f"Matrix device trust mode unsupported ({mode}); using strict_known."
        )
        return self._device_trust_mode_strict_known

    def _resolve_device_trust_allowlist(self) -> dict[str, set[str]]:
        allowlist = getattr(
            getattr(
                getattr(
                    getattr(self._config, "matrix", SimpleNamespace()),
                    "security",
                    SimpleNamespace(),
                ),
                "device_trust",
                SimpleNamespace(),
            ),
            "allowlist",
            [],
        )

        if not isinstance(allowlist, list):
            self._logging_gateway.warning(
                "Matrix device trust allowlist invalid; expected list."
            )
            return {}

        parsed_allowlist: dict[str, set[str]] = {}
        for entry in allowlist:
            user_id = None
            device_ids = None

            if isinstance(entry, dict):
                user_id = entry.get("user_id")
                device_ids = entry.get("device_ids")
            elif isinstance(entry, SimpleNamespace):
                user_id = getattr(entry, "user_id", None)
                device_ids = getattr(entry, "device_ids", None)

            if not isinstance(user_id, str) or not isinstance(device_ids, list):
                continue

            if user_id not in parsed_allowlist:
                parsed_allowlist[user_id] = set()
            parsed_allowlist[user_id].update(
                [str(device_id) for device_id in device_ids]
            )

        return parsed_allowlist

    def _log_untrusted_device(
        self,
        user_id: str,
        device_id: str,
        mode: str,
        reason: str,
    ) -> None:
        self._logging_gateway.warning(
            "Matrix device not trusted."
            f" user_id={user_id}"
            f" device_id={device_id}"
            f" mode={mode}"
            f" reason={reason}"
        )

    @staticmethod
    def _parse_sender_domain(sender_id: str) -> str | None:
        if not isinstance(sender_id, str):
            return None

        local_part, separator, domain_part = sender_id.partition(":")
        if separator == "" or not local_part.startswith("@") or domain_part.strip() == "":
            return None

        return domain_part

    def _direct_invites_only(self) -> bool:
        return bool(
            getattr(
                getattr(getattr(self._config, "matrix", SimpleNamespace()), "invites", None),
                "direct_only",
                True,
            )
        )

    def _resolve_media_max_download_bytes(self) -> int:
        max_download_bytes = getattr(
            getattr(getattr(self._config, "matrix", SimpleNamespace()), "media", None),
            "max_download_bytes",
            self._default_media_max_download_bytes,
        )
        try:
            max_download_bytes = int(max_download_bytes)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "Matrix media max download bytes invalid; using default."
            )
            return self._default_media_max_download_bytes

        if max_download_bytes <= 0:
            self._logging_gateway.warning(
                "Matrix media max download bytes invalid; using default."
            )
            return self._default_media_max_download_bytes

        return max_download_bytes

    def _resolve_media_allowed_mimetypes(self) -> list[str]:
        allowed_mimetypes = getattr(
            getattr(getattr(self._config, "matrix", SimpleNamespace()), "media", None),
            "allowed_mimetypes",
            self._default_media_allowed_mimetypes,
        )
        if not isinstance(allowed_mimetypes, list):
            self._logging_gateway.warning(
                "Matrix media allowed mimetypes invalid; using defaults."
            )
            return list(self._default_media_allowed_mimetypes)

        normalized = [
            str(pattern).strip().lower()
            for pattern in allowed_mimetypes
            if str(pattern).strip() != ""
        ]
        if not normalized:
            self._logging_gateway.warning(
                "Matrix media allowed mimetypes empty; using defaults."
            )
            return list(self._default_media_allowed_mimetypes)

        return normalized

    def _media_mimetype_allowed(self, mimetype: str) -> bool:
        normalized = mimetype.strip().lower()
        allowed_mimetypes = self._resolve_media_allowed_mimetypes()
        for pattern in allowed_mimetypes:
            if pattern.endswith("/*"):
                if normalized.startswith(pattern[:-1]):
                    return True
            elif normalized == pattern:
                return True

        return False

    def _cleanup_temp_file(self, file_path: str | None) -> None:
        if not isinstance(file_path, str) or file_path.strip() == "":
            return

        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except OSError:
            self._logging_gateway.warning(
                f"Matrix media cleanup failed for temp file: {file_path}."
            )

    async def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
        self._logging_gateway.debug(f"Verifying all user devices ({user_id}).")
        mode = self._resolve_device_trust_mode()
        allowlist = {}
        if mode == self._device_trust_mode_allowlist:
            allowlist = self._resolve_device_trust_allowlist()

        known_devices = await self._load_known_devices()
        try:
            user_devices = self.device_store[user_id]
        except KeyError:
            user_devices = {}

        for device_id, olm_device in user_devices.items():
            self._logging_gateway.debug(f"Found {device_id}.")
            if mode == self._device_trust_mode_strict_known:
                if device_id in known_devices.get(user_id, []):
                    self._logging_gateway.debug(f"Verifying {device_id}.")
                    self.verify_device(olm_device)
                else:
                    self._log_untrusted_device(
                        user_id=user_id,
                        device_id=device_id,
                        mode=mode,
                        reason="unknown_device",
                    )
                continue

            if mode == self._device_trust_mode_allowlist:
                if device_id in allowlist.get(user_id, set()):
                    self._logging_gateway.debug(f"Verifying {device_id}.")
                    self.verify_device(olm_device)
                else:
                    self._log_untrusted_device(
                        user_id=user_id,
                        device_id=device_id,
                        mode=mode,
                        reason="not_in_allowlist",
                    )
                continue

            # Ensure the list contains an entry for the user.
            if user_id not in known_devices.keys():
                known_devices[user_id] = []

            # If the device is not already in the known devices list for the user.
            if device_id not in known_devices[user_id]:
                # Add the device id to the list of known devices for the user.
                known_devices[user_id].append(device_id)

                # Verify the device.
                self._logging_gateway.debug(f"Verifying {device_id}.")
                self.verify_device(olm_device)

                # Persist changes to the known devices list.
                await self._save_known_devices(known_devices)

    def _log_skipped_callback(
        self,
        callback_name: str,
        event: object = None,
        reason: str = _callback_skip_reason_dm_scope,
    ) -> None:
        event_type = type(event).__name__ if event is not None else "UnknownEvent"
        self._logging_gateway.debug(
            "Matrix callback skipped."
            f" callback={callback_name}"
            f" event={event_type}"
            f" reason={reason}"
        )

    def _increment_matrix_metric(self, metric_name: str) -> None:
        metrics = getattr(self, "_matrix_metrics", None)
        if not isinstance(metrics, dict):
            metrics = {}
            self._matrix_metrics = metrics
        metrics[metric_name] = metrics.get(metric_name, 0) + 1

    def _track_matrix_decision(
        self,
        domain: str,
        action: str,
        reason: str,
        **fields,
    ) -> None:
        self._increment_matrix_metric(f"matrix.{domain}.{action}.{reason}")
        structured_fields = " ".join(
            f"{key}={value}" for key, value in fields.items() if value is not None
        )
        self._logging_gateway.debug(
            "Matrix decision"
            f" domain={domain}"
            f" action={action}"
            f" reason={reason}"
            f" {structured_fields}"
        )

    async def _dispatch_matrix_event_hook(
        self,
        callback_name: str,
        event: object = None,
        room: MatrixRoom | MatrixInvitedRoom | None = None,
        reason: str = _callback_skip_reason_dm_scope,
    ) -> None:
        if self._ipc_service is None:
            return

        if not callable(getattr(self._ipc_service, "handle_ipc_request", None)):
            return

        event_type = type(event).__name__ if event is not None else "UnknownEvent"
        room_id = getattr(room, "room_id", None)
        payload = IPCCommandRequest(
            platform="matrix",
            command=self._matrix_event_hook_command,
            data={
                "version": self._matrix_event_hook_payload_version,
                "callback": callback_name,
                "event_type": event_type,
                "reason": reason,
                "room_id": room_id if isinstance(room_id, str) else None,
                "sender": getattr(event, "sender", None),
                "content": (
                    event.content
                    if isinstance(getattr(event, "content", None), dict)
                    else None
                ),
                "source": (
                    event.source
                    if isinstance(getattr(event, "source", None), dict)
                    else None
                ),
                "event": event,
            },
        )
        self._start_matrix_ipc_worker()
        if self._matrix_ipc_queue is None:
            async def _dispatch_without_worker() -> None:
                try:
                    await self._dispatch_matrix_ipc_request(payload)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    self._logging_gateway.warning(
                        "Matrix event extension dispatch failed."
                        f" callback={callback_name}"
                        f" event={event_type}"
                        f" error={type(exc).__name__}: {exc}"
                    )

            asyncio.create_task(_dispatch_without_worker())
            return

        try:
            await asyncio.wait_for(
                self._matrix_ipc_queue.put(payload),
                timeout=self._matrix_ipc_enqueue_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._increment_matrix_metric("matrix.ipc.dispatch.enqueue_timeout")
            self._logging_gateway.warning(
                "Matrix event extension enqueue timed out; dispatching inline."
                f" callback={callback_name}"
                f" event={event_type}"
                f" enqueue_timeout_seconds={self._matrix_ipc_enqueue_timeout_seconds}"
            )
            try:
                await self._dispatch_matrix_ipc_request(payload)
                self._increment_matrix_metric(
                    "matrix.ipc.dispatch.fallback_inline_success"
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._increment_matrix_metric(
                    "matrix.ipc.dispatch.fallback_inline_failed"
                )
                self._logging_gateway.warning(
                    "Matrix event extension inline fallback dispatch failed."
                    f" callback={callback_name}"
                    f" event={event_type}"
                    f" error={type(exc).__name__}: {exc}"
                )

    async def _handle_non_core_event_callback(
        self,
        callback_name: str,
        event: object = None,
        room: MatrixRoom | MatrixInvitedRoom | None = None,
        reason: str = _callback_skip_reason_dm_scope,
    ) -> None:
        self._log_skipped_callback(
            callback_name=callback_name,
            event=event,
            reason=reason,
        )
        await self._dispatch_matrix_event_hook(
            callback_name=callback_name,
            event=event,
            room=room,
            reason=reason,
        )

    ## Callbacks.
    # Events
    async def _cb_megolm_event(self, _room: MatrixRoom, _event: MegolmEvent) -> None:
        """Handle MegolmEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_megolm_event",
            event=_event,
            room=_room,
        )

    async def _cb_invite_alias_event(
        self,
        _room: MatrixInvitedRoom,
        _event: InviteAliasEvent,
    ) -> None:
        """Handle InviteAliasEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_invite_alias_event",
            event=_event,
            room=_room,
        )

    async def _cb_invite_member_event(
        self, room: MatrixInvitedRoom, event: InviteMemberEvent
    ) -> None:
        """Handle InviteMemberEvents."""
        event_content = event.content if isinstance(event.content, dict) else {}

        # Filter out events that do not have membership set to invite.
        membership = event_content.get("membership")
        if membership is not None and membership != "invite":
            self._track_matrix_decision(
                domain="invites",
                action="ignored",
                reason="membership_not_invite",
                sender=event.sender,
                room_id=room.room_id,
                membership=membership,
            )
            return

        # Only process invites from allowed domains.
        # Federated servers need to be in the allowed domains list for their users
        # to initiate conversations with the assistant.
        allowed_domains: list = self._config.matrix.domains.allowed
        denied_domains: list = self._config.matrix.domains.denied
        sender_domain = self._parse_sender_domain(event.sender)
        if sender_domain is None:
            await self.room_leave(room.room_id)
            self._track_matrix_decision(
                domain="invites",
                action="rejected",
                reason="malformed_sender",
                sender=event.sender,
                room_id=room.room_id,
            )
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Malformed sender."
                f" ({event.sender})"
            )
            return

        if sender_domain not in allowed_domains or sender_domain in denied_domains:
            await self.room_leave(room.room_id)
            self._track_matrix_decision(
                domain="invites",
                action="rejected",
                reason="domain_not_allowed",
                sender=event.sender,
                room_id=room.room_id,
                sender_domain=sender_domain,
            )
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Domain"
                f" not allowed. ({event.sender})"
            )
            return

        # If the assistant is in limited-beta mode, only process invites from the
        # list of selected beta users.
        if self._config.mugen.beta.active:
            beta_users: list = self._config.matrix.beta.users
            if event.sender not in beta_users:
                await self.room_leave(room.room_id)
                self._track_matrix_decision(
                    domain="invites",
                    action="rejected",
                    reason="non_beta_user",
                    sender=event.sender,
                    room_id=room.room_id,
                )
                self._logging_gateway.warning(
                    "InviteMemberEvent: Rejected invitation. Reason:"
                    f" Non-beta user. ({event.sender})"
                )
                return

        # Only accept invites to Direct Messages for now.
        if self._direct_invites_only():
            is_direct = event_content.get("is_direct")
            if is_direct is not True:
                await self.room_leave(room.room_id)
                self._track_matrix_decision(
                    domain="invites",
                    action="rejected",
                    reason="not_direct_message",
                    sender=event.sender,
                    room_id=room.room_id,
                )
                self._logging_gateway.warning(
                    "InviteMemberEvent: Rejected invitation. Reason: Not direct"
                    f" message. ({event.sender})"
                )
                return

        # Verify user devices.
        await self.verify_user_devices(event.sender)

        # Join room.
        await self.join(room.room_id)
        await self._mark_room_as_direct(event.sender, room.room_id)
        self._track_matrix_decision(
            domain="invites",
            action="accepted",
            reason="joined",
            sender=event.sender,
            room_id=room.room_id,
        )

        # Get profile and add user to list of known users if required.
        resp = await self.get_profile(event.sender)
        if isinstance(resp, ProfileGetResponse):
            await self._user_service.add_known_user(
                event.sender, resp.displayname, room.room_id
            )

    async def _cb_invite_name_event(
        self, _room: MatrixInvitedRoom, _event: InviteNameEvent
    ) -> None:
        """Handle InviteNameEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_invite_name_event",
            event=_event,
            room=_room,
        )

    async def _cb_room_create_event(
        self, _room: MatrixRoom, _event: RoomCreateEvent
    ) -> None:
        """Handle RoomCreateEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_room_create_event",
            event=_event,
            room=_room,
        )

    async def _cb_key_verification_event(self, event: KeyVerificationEvent) -> None:
        """Handle key verification events."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_key_verification_event",
            event=event,
        )

    async def _cb_room_key_event(self, _event: RoomKeyEvent) -> None:
        """Handle RoomKeyEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_room_key_event",
            event=_event,
        )

    async def _cb_room_key_request(self, _event: RoomKeyRequest) -> None:
        """Handle RoomKeyRequests."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_room_key_request",
            event=_event,
        )

    async def _validate_message(self, room: MatrixRoom, message) -> bool:
        """Validate an incoming message"""
        sender_id = getattr(message, "sender", None)
        if self._parse_sender_domain(sender_id) is None:
            self._track_matrix_decision(
                domain="messages",
                action="rejected",
                reason="malformed_sender",
                sender=sender_id,
                room_id=room.room_id,
            )
            self._logging_gateway.warning(
                "RoomMessage: Rejected message. Reason: Malformed sender."
                f" ({sender_id})"
            )
            return False

        # Only process messages from direct chats for now.
        # And ignore the assistant's messages, otherwise it
        # will create a message loop.
        is_direct = await self._is_direct_message(room.room_id)
        if sender_id == self.user_id:
            self._track_matrix_decision(
                domain="messages",
                action="ignored",
                reason="self_message",
                sender=sender_id,
                room_id=room.room_id,
            )
            return False
        if not is_direct:
            self._track_matrix_decision(
                domain="messages",
                action="ignored",
                reason="room_not_direct",
                sender=sender_id,
                room_id=room.room_id,
            )
            self._logging_gateway.debug(
                "RoomMessage: Ignored message. Reason: Room not marked direct."
                f" ({room.room_id})"
            )
            return False

        # Verify user devices.
        await self.verify_user_devices(sender_id)

        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self.room_read_markers(room.room_id, message.event_id, message.event_id)
        self._track_matrix_decision(
            domain="messages",
            action="accepted",
            reason="validated",
            sender=sender_id,
            room_id=room.room_id,
        )

        return True

    async def _cb_room_message(self, room: MatrixRoom, message: RoomMessage) -> None:
        """Handle RoomMessage."""
        # Validate message before proceeding.
        if not await self._validate_message(room, message):
            return

        await self._emit_room_processing_signal(
            room_id=room.room_id,
            state=PROCESSING_STATE_START,
        )
        try:
            message_responses: list[dict] = []

            # Handle audio messages.
            if isinstance(message, RoomEncryptedAudio):
                get_media = await self._download_file(
                    message.source["content"]["file"],
                    message.source["content"]["info"],
                )
                if get_media:
                    try:
                        message_responses = (
                            await self._messaging_service.handle_audio_message(
                                platform="matrix",
                                room_id=room.room_id,
                                sender=message.sender,
                                message={
                                    "message": message,
                                    "file": get_media,
                                },
                            )
                        )
                    finally:
                        self._cleanup_temp_file(get_media)
            # Handle file messages.
            elif isinstance(message, RoomEncryptedFile):
                get_media = await self._download_file(
                    message.source["content"]["file"],
                    message.source["content"]["info"],
                )
                if get_media:
                    try:
                        message_responses = (
                            await self._messaging_service.handle_file_message(
                                platform="matrix",
                                room_id=room.room_id,
                                sender=message.sender,
                                message={
                                    "message": message,
                                    "file": get_media,
                                },
                            )
                        )
                    finally:
                        self._cleanup_temp_file(get_media)
            # Handle image messages.
            elif isinstance(message, RoomEncryptedImage):
                get_media = await self._download_file(
                    message.source["content"]["file"],
                    message.source["content"]["info"],
                )
                if get_media:
                    try:
                        message_responses = (
                            await self._messaging_service.handle_image_message(
                                platform="matrix",
                                room_id=room.room_id,
                                sender=message.sender,
                                message={
                                    "message": message,
                                    "file": get_media,
                                },
                            )
                        )
                    finally:
                        self._cleanup_temp_file(get_media)
            # Handle text messages.
            elif isinstance(message, RoomMessageText):
                message_responses = await self._messaging_service.handle_text_message(
                    platform="matrix",
                    room_id=room.room_id,
                    sender=message.sender,
                    message=message.body,
                )
            # Handle video messages.
            elif isinstance(message, RoomEncryptedVideo):
                get_media = await self._download_file(
                    message.source["content"]["file"],
                    message.source["content"]["info"],
                )
                if get_media:
                    try:
                        message_responses = (
                            await self._messaging_service.handle_video_message(
                                platform="matrix",
                                room_id=room.room_id,
                                sender=message.sender,
                                message={
                                    "message": message,
                                    "file": get_media,
                                },
                            )
                        )
                    finally:
                        self._cleanup_temp_file(get_media)

            await self._process_message_responses(
                room_id=room.room_id,
                message_responses=message_responses,
            )
        finally:
            await self._emit_room_processing_signal(
                room_id=room.room_id,
                state=PROCESSING_STATE_STOP,
            )

    async def _emit_room_processing_signal(
        self,
        *,
        room_id: str,
        state: str,
    ) -> None:
        try:
            normalized_state = normalize_processing_state(state)
            await self.room_typing(
                room_id,
                normalized_state == PROCESSING_STATE_START,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Failed to emit Matrix thinking signal "
                f"(room_id={room_id} state={state}): {exc}"
            )

    async def _cb_room_member_event(
        self, _room: MatrixRoom, _event: RoomMemberEvent
    ) -> None:
        """Handle RoomMemberEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_room_member_event",
            event=_event,
            room=_room,
        )

    async def _cb_tag_event(self, _event: TagEvent) -> None:
        """Handle TagEvents."""
        await self._handle_non_core_event_callback(
            callback_name="_cb_tag_event",
            event=_event,
        )

    # Responses
    async def _cb_sync_response(self, resp: SyncResponse):
        """Handle SyncResponses."""
        await self._keyval_storage_gateway.put_text(self._sync_key, resp.next_batch)
        self._sync_token = resp.next_batch

    ## Utilities.
    def _normalize_direct_rooms(self, payload: object) -> dict[str, list[str]]:
        if not isinstance(payload, dict):
            return {}

        direct_rooms: dict[str, list[str]] = {}
        for user_id, room_ids in payload.items():
            if not isinstance(user_id, str) or not isinstance(room_ids, list):
                continue
            direct_rooms[user_id] = [str(room_id) for room_id in room_ids]
        return direct_rooms

    async def _load_direct_rooms(self) -> dict[str, list[str]]:
        try:
            response = await self.list_direct_rooms()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Matrix direct room lookup failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return {}
        rooms = self._normalize_direct_rooms(getattr(response, "rooms", None))
        if rooms or isinstance(response, DirectRoomsResponse):
            return rooms

        self._logging_gateway.debug(
            "Matrix direct room list unavailable; continuing with fallback checks."
        )
        return {}

    async def _persist_direct_rooms(self, direct_rooms: dict[str, list[str]]) -> bool:
        try:
            path = Api._build_path(
                [
                    "user",
                    self.user_id,
                    "account_data",
                    self._direct_rooms_event_type,
                ],
                {"access_token": self.access_token},
            )
            response = await self._send(
                EmptyResponse,
                "PUT",
                path,
                json.dumps(direct_rooms),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Matrix direct room marker update failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return False

        if isinstance(response, EmptyResponse):
            return True

        self._logging_gateway.warning(
            "Matrix direct room marker update failed."
            f" response={type(response).__name__}"
        )
        return False

    async def _mark_room_as_direct(self, sender: str, room_id: str) -> None:
        if not isinstance(room_id, str) or room_id.strip() == "":
            return

        if isinstance(sender, str) and sender.strip() != "":
            direct_rooms = await self._load_direct_rooms()
            user_rooms = direct_rooms.get(sender, [])
            if room_id not in user_rooms:
                user_rooms.append(room_id)
                direct_rooms[sender] = user_rooms
                if not await self._persist_direct_rooms(direct_rooms):
                    self._logging_gateway.warning(
                        "Matrix direct room marker not persisted."
                        f" sender={sender}"
                        f" room_id={room_id}"
                    )

        self._direct_room_ids.add(room_id)

    async def _is_legacy_direct_message(self, room_id: str) -> bool:
        """Fallback for rooms flagged by legacy muGen markers."""
        room_state = await self.room_get_state(room_id)
        events = getattr(room_state, "events", [])
        if not isinstance(events, list):
            return False

        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") != self._legacy_direct_flags_key:
                continue
            content = event.get("content")
            if not isinstance(content, dict):
                continue
            if content.get("m.direct") in [1, True]:
                return True

        return False

    async def _is_direct_message(self, room_id: str) -> bool:
        """Indicate if the room is marked direct via Matrix account data."""
        if room_id in self._direct_room_ids:
            return True

        direct_rooms = await self._load_direct_rooms()
        for direct_room_ids in direct_rooms.values():
            if room_id in direct_room_ids:
                self._direct_room_ids.add(room_id)
                return True

        # Retain compatibility with rooms marked before m.direct support.
        return await self._is_legacy_direct_message(room_id)

    async def _process_message_responses(
        self, room_id: str, message_responses: list[dict]
    ) -> None:

        self._logging_gateway.debug("Send responses to user.")

        for response in message_responses:
            match response["type"]:
                case "audio":
                    await self._send_audio_message(
                        room_id=room_id,
                        file=response["file"],
                        audio_info=response["info"],
                    )
                case "file":
                    await self._send_file_message(
                        room_id=room_id,
                        file=response["file"],
                    )
                case "image":
                    await self._send_image_message(
                        room_id=room_id,
                        file=response["file"],
                        image_info=response["info"],
                    )
                case "text":
                    await self._send_text_message(
                        room_id=room_id,
                        body=response["content"],
                    )
                case "video":
                    await self._send_video_message(
                        room_id=room_id,
                        file=response["file"],
                        video_info=response["info"],
                    )
                case _:
                    pass

    async def _room_send_with_unverified_self_device_fallback(
        self,
        room_id: str,
        content: dict,
    ) -> None:
        try:
            await self.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
        except OlmUnverifiedDeviceError as exc:
            unverified_device = getattr(exc, "device", None)
            unverified_user_id = getattr(unverified_device, "user_id", None)
            if unverified_user_id != self.user_id:
                raise

            unverified_device_id = getattr(unverified_device, "device_id", None)
            if unverified_device_id is None:
                unverified_device_id = getattr(unverified_device, "id", None)

            self._logging_gateway.warning(
                "Matrix send encountered unverified local device; retrying with"
                " ignore_unverified_devices."
                f" user_id={unverified_user_id}"
                f" device_id={unverified_device_id}"
                f" room_id={room_id}"
            )
            await self.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=True,
            )

    async def _send_audio_message(
        self,
        room_id: str,
        file: dict,
        audio_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self._room_send_with_unverified_self_device_fallback(
                    room_id=room_id,
                    content={
                        "msgtype": "m.audio",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "duration": audio_info["duration"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._log_send_failure("DefaultMatrixClient: Error sending audio message.")

    async def _send_file_message(
        self,
        room_id: str,
        file: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self._room_send_with_unverified_self_device_fallback(
                    room_id=room_id,
                    content={
                        "msgtype": "m.file",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._log_send_failure("DefaultMatrixClient: Error sending file message.")

    async def _send_image_message(
        self,
        room_id: str,
        file: dict,
        image_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self._room_send_with_unverified_self_device_fallback(
                    room_id=room_id,
                    content={
                        "msgtype": "m.image",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "h": image_info["height"],
                            "w": image_info["width"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._log_send_failure("DefaultMatrixClient: Error sending image message.")

    async def _send_text_message(self, room_id: str, body: str) -> None:
        try:
            await self._room_send_with_unverified_self_device_fallback(
                room_id=room_id,
                content={
                    "msgtype": "m.text",
                    "body": body,
                },
            )
        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._log_send_failure("DefaultMatrixClient: Error sending text message.")

    async def _send_video_message(
        self,
        room_id: str,
        file: dict,
        video_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self._room_send_with_unverified_self_device_fallback(
                    room_id=room_id,
                    content={
                        "msgtype": "m.video",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "duration": video_info["duration"],
                            "h": video_info["height"],
                            "w": video_info["width"],
                        },
                    },
                )
        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._log_send_failure("DefaultMatrixClient: Error sending video message.")

    async def _download_file(self, file: dict, info: dict) -> str | None:
        if not isinstance(info, dict):
            self._track_matrix_decision(
                domain="media",
                action="rejected",
                reason="invalid_metadata",
            )
            self._logging_gateway.warning(
                "Matrix media download rejected. Reason: Invalid metadata payload."
            )
            return None

        mimetype = info.get("mimetype")
        if not isinstance(mimetype, str) or mimetype.strip() == "":
            self._track_matrix_decision(
                domain="media",
                action="rejected",
                reason="missing_mimetype",
            )
            self._logging_gateway.warning(
                "Matrix media download rejected. Reason: Missing mimetype."
            )
            return None

        mimetype = mimetype.strip().lower()
        if not self._media_mimetype_allowed(mimetype):
            self._track_matrix_decision(
                domain="media",
                action="rejected",
                reason="mimetype_not_allowed",
                mimetype=mimetype,
            )
            self._logging_gateway.warning(
                "Matrix media download rejected."
                f" Reason: Mimetype not allowed ({mimetype})."
            )
            return None

        max_download_bytes = self._resolve_media_max_download_bytes()
        declared_size = info.get("size")
        if isinstance(declared_size, int) and declared_size > max_download_bytes:
            self._track_matrix_decision(
                domain="media",
                action="rejected",
                reason="declared_size_exceeded",
                declared_size=declared_size,
                max_download_bytes=max_download_bytes,
            )
            self._logging_gateway.warning(
                "Matrix media download rejected."
                f" Reason: Declared size exceeds limit ({declared_size} > {max_download_bytes})."
            )
            return None

        # Guess extension using mimetype.
        extension = mimetypes.guess_extension(mimetype)

        # Successfully guessed extension.
        if extension:
            # Use a tempfile for savng encrypted file.
            with tempfile.NamedTemporaryFile(suffix=extension) as tf:

                # Download the encrypted file.
                resp = await self.download(
                    file["url"],
                    save_to=tf.name,
                )

                # Download successful.
                if isinstance(resp, DiskDownloadResponse):
                    downloaded_size = os.path.getsize(tf.name)
                    if downloaded_size > max_download_bytes:
                        self._track_matrix_decision(
                            domain="media",
                            action="rejected",
                            reason="downloaded_size_exceeded",
                            downloaded_size=downloaded_size,
                            max_download_bytes=max_download_bytes,
                        )
                        self._logging_gateway.warning(
                            "Matrix media download rejected."
                            f" Reason: Downloaded size exceeds limit ({downloaded_size} > {max_download_bytes})."
                        )
                        return None

                    # Open ecrypted file for reading.
                    with open(tf.name, "rb") as tfb:
                        try:
                            # Decrypt file.
                            decrypted_file = nio.crypto.decrypt_attachment(
                                tfb.read(),
                                key=file["key"]["k"],
                                hash=file["hashes"]["sha256"],
                                iv=file["iv"],
                            )

                            # Use tempfile for saving decrypted file.
                            with tempfile.NamedTemporaryFile(
                                suffix=extension, delete=False
                            ) as df:
                                df.write(decrypted_file)
                                self._track_matrix_decision(
                                    domain="media",
                                    action="accepted",
                                    reason="downloaded",
                                    mimetype=mimetype,
                                )
                                return df.name
                        except Exception as exc:  # pylint: disable=broad-exception-caught
                            self._track_matrix_decision(
                                domain="media",
                                action="rejected",
                                reason="decrypt_failed",
                            )
                            self._logging_gateway.warning(
                                "Matrix media decryption failed."
                                f" error={type(exc).__name__}: {exc}"
                            )
                            return None

                self._track_matrix_decision(
                    domain="media",
                    action="rejected",
                    reason="download_response_unexpected",
                )
                return None

        self._track_matrix_decision(
            domain="media",
            action="rejected",
            reason="extension_unknown",
            mimetype=mimetype,
        )
        return None

    async def _upload_file(self, file: dict):
        resp = None
        maybe_keys = None

        if isinstance(file["uri"], BytesIO):
            resp, maybe_keys = await self._upload_in_memory_file(file)
        else:
            resp, maybe_keys = await self._upload_disk_file(file)

        return resp, maybe_keys

    async def _upload_in_memory_file(
        self,
        file: dict,
        encrypt: bool = True,
    ):
        return await self.upload(
            file["uri"],
            content_type=file["type"],
            filename=file["name"],
            filesize=file["size"],
            encrypt=encrypt,
        )

    async def _upload_disk_file(
        self,
        file: dict,
        encrypt: bool = True,
    ):
        async with aiofiles.open(file["uri"], "r+b") as f:
            return await self.upload(
                f,
                content_type=file["type"],
                filename=file["name"],
                filesize=file["size"],
                encrypt=encrypt,
            )
