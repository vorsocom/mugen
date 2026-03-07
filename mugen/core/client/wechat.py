"""Provides an implementation of IWeChatClient."""

__all__ = ["DefaultWeChatClient", "MultiProfileWeChatClient", "WeChatAPIResponse"]

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPMethod
from io import BytesIO
import json
import os
import tempfile
from types import SimpleNamespace
from typing import Any, TypedDict
import uuid

import aiohttp

from mugen.core.client.runtime_profile_manager import SimpleProfileClientManager
from mugen.core.contract.client.wechat import IWeChatClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    normalize_processing_state,
)


class WeChatAPIResponse(TypedDict):
    """Represents a normalized WeChat API response envelope."""

    ok: bool
    status: int | None
    data: dict[str, Any] | None
    error: str | None
    raw: str | None


class DefaultWeChatClient(IWeChatClient):
    """Default WeChat adapter for Official Account and WeCom providers."""

    _provider_official_account = "official_account"
    _provider_wecom = "wecom"

    _default_http_timeout_seconds: float = 10.0
    _default_max_download_bytes: int = 20 * 1024 * 1024
    _default_max_api_retries: int = 2
    _default_retry_backoff_seconds: float = 0.5
    _default_typing_enabled: bool = True

    _base_url_official_account = "https://api.weixin.qq.com/cgi-bin"
    _base_url_wecom = "https://qyapi.weixin.qq.com/cgi-bin"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        ipc_service: IIPCService | None = None,
        keyval_storage_gateway: IKeyValStorageGateway | None = None,
        logging_gateway: ILoggingGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
    ) -> None:
        self._client_session: aiohttp.ClientSession | None = None
        self._config = config
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        self._provider = self._resolve_provider()
        self._base_url = self._resolve_base_url()
        self._http_timeout_seconds = self._resolve_http_timeout_seconds()
        self._max_download_bytes = self._resolve_max_download_bytes()
        self._max_api_retries = self._resolve_max_api_retries()
        self._retry_backoff_seconds = self._resolve_retry_backoff_seconds()
        self._typing_enabled = self._resolve_typing_enabled()
        self._shutdown_timeout_seconds = self._resolve_shutdown_timeout_seconds()

        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def _resolve_provider(self) -> str:
        provider = str(
            getattr(getattr(self._config, "wechat", SimpleNamespace()), "provider", "")
        ).strip().lower()
        if provider in {
            self._provider_official_account,
            self._provider_wecom,
        }:
            return provider
        raise RuntimeError(
            "Invalid configuration: wechat.provider must be 'official_account' or 'wecom'."
        )

    def _resolve_base_url(self) -> str:
        if self._provider == self._provider_wecom:
            return self._base_url_wecom
        return self._base_url_official_account

    def _resolve_http_timeout_seconds(self) -> float:
        raw_timeout = getattr(
            getattr(getattr(self._config, "wechat", None), "api", None),
            "timeout_seconds",
            None,
        )
        timeout = parse_optional_positive_finite_float(
            raw_timeout,
            "wechat.api.timeout_seconds",
        )
        if timeout is None:
            return self._default_http_timeout_seconds
        return timeout

    def _resolve_max_download_bytes(self) -> int:
        raw_limit = getattr(
            getattr(getattr(self._config, "wechat", None), "api", None),
            "max_download_bytes",
            self._default_max_download_bytes,
        )
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = self._default_max_download_bytes

        if limit <= 0:
            return self._default_max_download_bytes

        return limit

    def _resolve_max_api_retries(self) -> int:
        raw_retries = getattr(
            getattr(getattr(self._config, "wechat", None), "api", None),
            "max_api_retries",
            self._default_max_api_retries,
        )
        try:
            retries = int(raw_retries)
        except (TypeError, ValueError):
            retries = self._default_max_api_retries

        if retries < 0:
            return self._default_max_api_retries

        return retries

    def _resolve_retry_backoff_seconds(self) -> float:
        raw_backoff = getattr(
            getattr(getattr(self._config, "wechat", None), "api", None),
            "retry_backoff_seconds",
            None,
        )
        return parse_nonnegative_finite_float(
            raw_backoff,
            field_name="wechat.api.retry_backoff_seconds",
            default=self._default_retry_backoff_seconds,
        )

    def _resolve_typing_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "wechat", None), "typing", None),
            "enabled",
            self._default_typing_enabled,
        )
        return parse_bool_flag(raw_enabled, self._default_typing_enabled)

    def _resolve_shutdown_timeout_seconds(self) -> float:
        settings = parse_runtime_bootstrap_settings(self._config)
        return float(settings.shutdown_timeout_seconds)

    @staticmethod
    def _build_api_response(
        *,
        ok: bool,
        status: int | None,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        raw: str | None = None,
    ) -> WeChatAPIResponse:
        return {
            "ok": ok,
            "status": status,
            "data": data,
            "error": error,
            "raw": raw,
        }

    @staticmethod
    def _parse_response_payload(response_text: str | None) -> dict[str, Any] | None:
        if response_text in [None, ""]:
            return None

        try:
            parsed = json.loads(response_text)
        except (TypeError, ValueError):
            return None

        if isinstance(parsed, dict):
            return parsed

        return None

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        return status == 429 or status >= 500

    @staticmethod
    def _provider_error(payload: dict[str, Any] | None) -> str | None:
        if not isinstance(payload, dict):
            return None
        err_code = payload.get("errcode")
        if err_code in [None, 0, "0"]:
            return None
        err_msg = payload.get("errmsg")
        return f"errcode={err_code} errmsg={err_msg}"

    def _resolve_correlation_id(self, correlation_id: str | None) -> str:
        if isinstance(correlation_id, str) and correlation_id != "":
            return correlation_id
        return self._new_correlation_id()

    async def _wait_before_retry(
        self,
        *,
        attempt: int,
        correlation_id: str,
        method: str,
        path: str,
        reason: str,
    ) -> None:
        delay_seconds = self._retry_backoff_seconds * (2**attempt)
        self._logging_gateway.warning(
            f"[cid={correlation_id}] Retrying WeChat API call for {method} {path} in "
            f"{delay_seconds:.2f}s ({reason}) attempt={attempt + 1}."
        )
        await asyncio.sleep(delay_seconds)

    async def init(self) -> None:
        self._logging_gateway.debug("DefaultWeChatClient.init")
        if (
            self._client_session is not None
            and getattr(self._client_session, "closed", False) is False
        ):
            return

        timeout = aiohttp.ClientTimeout(total=self._http_timeout_seconds)
        self._client_session = aiohttp.ClientSession(timeout=timeout)

    async def verify_startup(self) -> bool:
        token = await self._ensure_access_token()
        if token in [None, ""]:
            return False
        return True

    async def close(self) -> None:
        self._logging_gateway.debug("DefaultWeChatClient.close")
        if self._client_session is None:
            return

        if getattr(self._client_session, "closed", False) is True:
            self._client_session = None
            return

        try:
            await asyncio.wait_for(
                self._client_session.close(),
                timeout=self._shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._logging_gateway.error("WeChat client session close timed out.")
            raise RuntimeError("WeChat client session close timed out.") from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "WeChat client session close failed "
                f"error_type={type(exc).__name__} error={exc}"
            )
            raise RuntimeError(
                f"WeChat client session close failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            self._client_session = None

    async def _ensure_access_token(self) -> str | None:
        if (
            isinstance(self._access_token, str)
            and self._access_token != ""
            and isinstance(self._access_token_expires_at, datetime)
            and self._access_token_expires_at > (self._now_utc() + timedelta(seconds=60))
        ):
            return self._access_token

        response = await self._fetch_access_token()
        payload = response.get("data") if isinstance(response, dict) else None
        if not isinstance(payload, dict):
            return None

        token = payload.get("access_token")
        if not isinstance(token, str) or token == "":
            return None

        expires_in = payload.get("expires_in", 7200)
        try:
            expires_seconds = int(expires_in)
        except (TypeError, ValueError):
            expires_seconds = 7200
        if expires_seconds <= 0:
            expires_seconds = 7200

        self._access_token = token
        self._access_token_expires_at = self._now_utc() + timedelta(seconds=expires_seconds)
        return token

    async def _fetch_access_token(self) -> WeChatAPIResponse:
        if self._provider == self._provider_wecom:
            corp_id = str(self._config.wechat.wecom.corp_id)
            corp_secret = str(self._config.wechat.wecom.corp_secret)
            return await self._request(
                method=HTTPMethod.GET,
                url=f"{self._base_url}/gettoken",
                params={
                    "corpid": corp_id,
                    "corpsecret": corp_secret,
                },
                include_token=False,
            )

        app_id = str(self._config.wechat.official_account.app_id)
        app_secret = str(self._config.wechat.official_account.app_secret)
        return await self._request(
            method=HTTPMethod.GET,
            url=f"{self._base_url}/token",
            params={
                "grant_type": "client_credential",
                "appid": app_id,
                "secret": app_secret,
            },
            include_token=False,
        )

    @asynccontextmanager
    async def _request_context(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        payload: dict[str, Any] | None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ):
        if self._client_session is None or self._client_session.closed:
            raise RuntimeError("Client session unavailable.")

        request_method = method.upper()
        kwargs: dict[str, Any] = {}
        if params is not None:
            kwargs["params"] = params
        if payload is not None:
            kwargs["json"] = payload
        if data is not None:
            kwargs["data"] = data
        if headers is not None:
            kwargs["headers"] = headers

        if request_method == HTTPMethod.GET:
            response = await self._client_session.get(url, **kwargs)
        else:
            response = await self._client_session.post(url, **kwargs)

        try:
            yield response
        finally:
            response.release()
            response.close()

    async def _request(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        include_token: bool = True,
        correlation_id: str | None = None,
    ) -> WeChatAPIResponse:
        cid = self._resolve_correlation_id(correlation_id)
        token_params = dict(params or {})

        if include_token:
            access_token = await self._ensure_access_token()
            if access_token in [None, ""]:
                return self._build_api_response(
                    ok=False,
                    status=None,
                    error="access token unavailable",
                )
            token_params["access_token"] = access_token

        last_response = self._build_api_response(
            ok=False,
            status=None,
            error="request not attempted",
        )
        last_exception: Exception | None = None

        for attempt in range(self._max_api_retries + 1):
            try:
                async with self._request_context(
                    method=method,
                    url=url,
                    params=token_params,
                    payload=payload,
                    data=data,
                    headers=headers,
                ) as response:
                    response_text = await response.text()
                    parsed = self._parse_response_payload(response_text)
                    status = int(response.status)

                    provider_error = self._provider_error(parsed)
                    if 200 <= status < 300 and provider_error is None:
                        return self._build_api_response(
                            ok=True,
                            status=status,
                            data=parsed,
                            raw=response_text,
                        )

                    last_response = self._build_api_response(
                        ok=False,
                        status=status,
                        data=parsed,
                        error=(
                            provider_error
                            if provider_error is not None
                            else f"http status {status}"
                        ),
                        raw=response_text,
                    )

                    if attempt < self._max_api_retries and self._is_retryable_status(status):
                        await self._wait_before_retry(
                            attempt=attempt,
                            correlation_id=cid,
                            method=method,
                            path=url,
                            reason=f"status={status}",
                        )
                        continue
                    return last_response
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exception = exc
                self._logging_gateway.warning(
                    f"[cid={cid}] WeChat API call failed "
                    f"attempt={attempt + 1} error_type={type(exc).__name__} error={exc}"
                )
                if attempt < self._max_api_retries:
                    await self._wait_before_retry(
                        attempt=attempt,
                        correlation_id=cid,
                        method=method,
                        path=url,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue

        if last_exception is not None:
            return self._build_api_response(
                ok=False,
                status=None,
                error=f"request error: {type(last_exception).__name__}: {last_exception}",
            )
        return last_response

    async def _call_api(
        self,
        *,
        path: str,
        method: str = HTTPMethod.POST,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        include_token: bool = True,
        correlation_id: str | None = None,
    ) -> WeChatAPIResponse:
        return await self._request(
            method=method,
            url=f"{self._base_url}/{path.lstrip('/')}",
            params=params,
            payload=payload,
            data=data,
            headers=headers,
            include_token=include_token,
            correlation_id=correlation_id,
        )

    async def _download_binary(
        self,
        *,
        path: str,
        params: dict[str, Any],
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        cid = self._resolve_correlation_id(correlation_id)

        access_token = await self._ensure_access_token()
        if access_token in [None, ""]:
            return None

        token_params = dict(params)
        token_params["access_token"] = access_token
        url = f"{self._base_url}/{path.lstrip('/')}"

        try:
            async with self._request_context(
                method=HTTPMethod.GET,
                url=url,
                params=token_params,
                payload=None,
            ) as response:
                status = int(response.status)
                body = await response.read()
                if not (200 <= status < 300):
                    self._logging_gateway.error(
                        f"[cid={cid}] WeChat media download failed status={status}."
                    )
                    return None

                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "application/json" in content_type:
                    payload = self._parse_response_payload(body.decode("utf-8", errors="ignore"))
                    self._logging_gateway.error(
                        f"[cid={cid}] WeChat media download returned JSON payload={payload}."
                    )
                    return None

                if len(body) > self._max_download_bytes:
                    self._logging_gateway.error(
                        f"[cid={cid}] WeChat media download exceeded max bytes."
                    )
                    return None

                suffix = ".bin"
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    delete=False,
                    suffix=suffix,
                    prefix="mugen_wechat_",
                ) as file_handle:
                    file_handle.write(body)
                    file_path = file_handle.name

                return {
                    "path": file_path,
                    "size": len(body),
                    "mime_type": response.headers.get("Content-Type"),
                }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                f"[cid={cid}] WeChat media download failed "
                f"error_type={type(exc).__name__} error={exc}."
            )
            return None

    def _provider_send_path(self) -> str:
        if self._provider == self._provider_wecom:
            return "message/send"
        return "message/custom/send"

    def _provider_typing_path(self) -> str:
        if self._provider == self._provider_wecom:
            return "message/typing"
        return "message/custom/typing"

    def _build_message_payload(
        self,
        *,
        recipient: str,
        msg_type: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        if self._provider == self._provider_wecom:
            return {
                "touser": recipient,
                "msgtype": msg_type,
                "agentid": int(self._config.wechat.wecom.agent_id),
                msg_type: content,
                "safe": 0,
            }
        return {
            "touser": recipient,
            "msgtype": msg_type,
            msg_type: content,
        }

    @staticmethod
    def _extract_media_id(payload: dict[str, Any]) -> str | None:
        for key in ("id", "media_id"):
            value = payload.get(key)
            if isinstance(value, str) and value != "":
                return value
        return None

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_to: str | None = None,
    ) -> dict | None:
        _ = reply_to
        payload = self._build_message_payload(
            recipient=recipient,
            msg_type="text",
            content={"content": text},
        )
        return await self._call_api(
            path=self._provider_send_path(),
            payload=payload,
        )

    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        _ = reply_to
        media_id = self._extract_media_id(audio)
        if media_id in [None, ""]:
            self._logging_gateway.error("Missing audio media_id for WeChat response.")
            return None
        payload = self._build_message_payload(
            recipient=recipient,
            msg_type="voice",
            content={"media_id": media_id},
        )
        return await self._call_api(path=self._provider_send_path(), payload=payload)

    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        _ = reply_to
        media_id = self._extract_media_id(file)
        if media_id in [None, ""]:
            self._logging_gateway.error("Missing file media_id for WeChat response.")
            return None
        payload = self._build_message_payload(
            recipient=recipient,
            msg_type="file",
            content={"media_id": media_id},
        )
        return await self._call_api(path=self._provider_send_path(), payload=payload)

    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        _ = reply_to
        media_id = self._extract_media_id(image)
        if media_id in [None, ""]:
            self._logging_gateway.error("Missing image media_id for WeChat response.")
            return None
        payload = self._build_message_payload(
            recipient=recipient,
            msg_type="image",
            content={"media_id": media_id},
        )
        return await self._call_api(path=self._provider_send_path(), payload=payload)

    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        _ = reply_to
        media_id = self._extract_media_id(video)
        if media_id in [None, ""]:
            self._logging_gateway.error("Missing video media_id for WeChat response.")
            return None
        payload = self._build_message_payload(
            recipient=recipient,
            msg_type="video",
            content={"media_id": media_id},
        )
        return await self._call_api(path=self._provider_send_path(), payload=payload)

    async def send_raw_message(self, *, payload: dict[str, Any]) -> dict | None:
        return await self._call_api(path=self._provider_send_path(), payload=payload)

    async def upload_media(
        self,
        *,
        file_path: str | BytesIO,
        media_type: str,
    ) -> dict | None:
        if not isinstance(media_type, str) or media_type.strip() == "":
            self._logging_gateway.error("Invalid media type for WeChat upload.")
            return None

        data = aiohttp.FormData()

        if isinstance(file_path, str):
            if os.path.isfile(file_path) is not True:
                self._logging_gateway.error("WeChat upload file does not exist.")
                return None
            with open(file_path, "rb") as upload_file:
                file_bytes = upload_file.read()
            data.add_field(
                name="media",
                value=file_bytes,
                filename=os.path.basename(file_path),
            )
        elif isinstance(file_path, BytesIO):
            data.add_field(
                name="media",
                value=file_path.getvalue(),
                filename="upload.bin",
            )
        else:
            self._logging_gateway.error("Invalid upload payload for WeChat media upload.")
            return None

        return await self._call_api(
            path="media/upload",
            method=HTTPMethod.POST,
            params={"type": media_type.strip().lower()},
            data=data,
        )

    async def download_media(
        self,
        *,
        media_id: str,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        _ = mime_type
        if not isinstance(media_id, str) or media_id == "":
            return None
        return await self._download_binary(
            path="media/get",
            params={"media_id": media_id},
        )

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = message_id
        if self._typing_enabled is not True:
            return None

        normalized_state = normalize_processing_state(state)
        command = "Typing" if normalized_state == PROCESSING_STATE_START else "CancelTyping"

        payload = {"touser": recipient, "command": command}
        response = await self._call_api(
            path=self._provider_typing_path(),
            payload=payload,
        )
        if not isinstance(response, dict):
            return False
        return bool(response.get("ok"))


class MultiProfileWeChatClient(SimpleProfileClientManager, IWeChatClient):
    """WeChat client manager that multiplexes configured runtime profiles."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ) -> None:
        super().__init__(
            platform="wechat",
            client_cls=DefaultWeChatClient,
            config=config,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
        reply_to: str | None = None,
    ) -> dict | None:
        return await self._client_for().send_text_message(
            recipient=recipient,
            text=text,
            reply_to=reply_to,
        )

    async def send_audio_message(
        self,
        *,
        recipient: str,
        audio: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        return await self._client_for().send_audio_message(
            recipient=recipient,
            audio=audio,
            reply_to=reply_to,
        )

    async def send_file_message(
        self,
        *,
        recipient: str,
        file: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        return await self._client_for().send_file_message(
            recipient=recipient,
            file=file,
            reply_to=reply_to,
        )

    async def send_image_message(
        self,
        *,
        recipient: str,
        image: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        return await self._client_for().send_image_message(
            recipient=recipient,
            image=image,
            reply_to=reply_to,
        )

    async def send_video_message(
        self,
        *,
        recipient: str,
        video: dict[str, Any],
        reply_to: str | None = None,
    ) -> dict | None:
        return await self._client_for().send_video_message(
            recipient=recipient,
            video=video,
            reply_to=reply_to,
        )

    async def send_raw_message(self, *, payload: dict[str, Any]) -> dict | None:
        return await self._client_for().send_raw_message(payload=payload)

    async def upload_media(
        self,
        *,
        file_path: str | BytesIO,
        media_type: str,
    ) -> dict | None:
        return await self._client_for().upload_media(
            file_path=file_path,
            media_type=media_type,
        )

    async def download_media(
        self,
        *,
        media_id: str,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._client_for().download_media(
            media_id=media_id,
            mime_type=mime_type,
        )

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        return await self._client_for().emit_processing_signal(
            recipient,
            state=state,
            message_id=message_id,
        )
