"""Provides an implementation of the nio.AsyncClient."""

__all__ = ["CustomAsyncClient"]

import asyncio
import sys
from typing import Coroutine, Optional

from nio import AsyncClient, LoginResponse

from nio.api import _FilterT
from nio.client.async_client import AsyncClientConfig
from nio.client.base_client import logged_in

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


class CustomAsyncClient(AsyncClient):
    """A custom implementation of nio.AsyncClient."""

    _ipc_callback: Coroutine

    def __init__(
        self,
        homeserver: str,
        user: str = "",
        device_id: str | None = "",
        store_path: str | None = "",
        config: AsyncClientConfig | None = None,
        ssl: bool | None = None,
        proxy: str | None = None,
        ipc_queue: asyncio.Queue = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
    ):
        super().__init__(homeserver, user, device_id, store_path, config, ssl, proxy)
        self._ipc_queue = ipc_queue
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    async def __aenter__(self):
        """Initialisation."""
        if self._keyval_storage_gateway.get("client_access_token") is None:
            # Load password and device name from storage.
            pw = self._keyval_storage_gateway.get("matrix_client_password")
            dn = self._keyval_storage_gateway.get("matrix_client_device_name")

            # Attempt  password login.
            resp = await self.login(pw, dn)

            # check login successful
            if isinstance(resp, LoginResponse):
                self._logging_gateway.debug("Password login successful.")
                self._logging_gateway.debug("Saving credentials.")

                # Save credentials.
                self._keyval_storage_gateway.put(
                    "client_access_token", resp.access_token
                )
                self._keyval_storage_gateway.put("client_device_id", resp.device_id)
                self._keyval_storage_gateway.put("client_user_id", resp.user_id)
            else:
                self._logging_gateway.debug("Password login failed.")
                sys.exit(1)
            sys.exit(0)

        # Otherwise the config file exists, so we'll use the stored credentials.
        self._logging_gateway.info("Logging in using saved credentials.")
        # open the file in read-only mode.
        self.access_token = self._keyval_storage_gateway.get("client_access_token")
        self.device_id = self._keyval_storage_gateway.get("client_device_id")
        self._logging_gateway.info(f"Device ID: {self.device_id}")
        self.user_id = self._keyval_storage_gateway.get("client_user_id")
        self.load_store()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Finalisation."""
        await self.client_session.close()

    # pylint: disable=too-many-arguments,too-many-locals
    @logged_in
    async def sync_forever(
        self,
        timeout: Optional[int] = None,
        sync_filter: _FilterT = None,
        since: Optional[str] = None,
        full_state: Optional[bool] = None,
        loop_sleep_time: Optional[int] = None,
        first_sync_filter: _FilterT = None,
        set_presence: Optional[str] = None,
    ):
        """Continuously sync with the configured homeserver.

        This method calls the sync method in a loop. To react to events event
        callbacks should be configured.

        The loop also makes sure to handle other required requests between
        syncs, including to_device messages and sending encryption keys if
        required. To react to the responses a response callback should be
        added.

        Args:
            timeout (int, optional): The maximum time that the server should
                wait for new events before it should return the request
                anyways, in milliseconds.
                If ``0``, no timeout is applied.
                If ``None``, ``AsyncClient.config.request_timeout`` is used.
                In any case, ``0`` is always used for the first sync.
                If a timeout is applied and the server fails to return after
                15 seconds of expected timeout,
                the client will timeout by itself.

            sync_filter (Union[None, str, Dict[Any, Any]):
                A filter ID that can be obtained from
                ``AsyncClient.upload_filter()`` (preferred),
                or filter dict that should be used for sync requests.

            full_state (bool, optional): Controls whether to include the full
                state for all rooms the user is a member of. If this is set to
                true, then all state events will be returned, even if since is
                non-empty. The timeline will still be limited by the since
                parameter. This argument will be used only for the first sync
                request.

            since (str, optional): A token specifying a point in time where to
                continue the sync from. Defaults to the last sync token we
                received from the server using this API call. This argument
                will be used only for the first sync request, the subsequent
                sync requests will use the token from the last sync response.

            loop_sleep_time (int, optional): The sleep time, if any, between
                successful sync loop iterations in milliseconds.

            first_sync_filter (Union[None, str, Dict[Any, Any]):
                A filter ID that can be obtained from
                ``AsyncClient.upload_filter()`` (preferred),
                or filter dict to use for the first sync request only.
                If `None` (default), the `sync_filter` parameter's value
                is used.
                To have no filtering for the first sync regardless of
                `sync_filter`'s value, pass `{}`.

            set_presence (str, optional): The presence state.
                One of: ["online", "offline", "unavailable"]
        """

        first_sync = True

        while True:
            try:
                use_filter = first_sync_filter if first_sync else sync_filter
                use_timeout = 0 if first_sync else timeout

                tasks = []

                # Make sure that if this is our first sync that the sync happens
                # before the other requests, this helps to ensure that after one
                # fired synced event the state is indeed fully synced.
                if first_sync:
                    presence = set_presence or self._presence
                    sync_response = await self.sync(
                        use_timeout, use_filter, since, full_state, presence
                    )
                    await self.run_response_callbacks([sync_response])
                else:
                    presence = set_presence or self._presence
                    tasks = [
                        asyncio.ensure_future(coro)
                        for coro in (
                            self.sync(
                                use_timeout, use_filter, since, full_state, presence
                            ),
                            self.send_to_device_messages(),
                        )
                    ]

                if self.should_upload_keys:
                    tasks.append(asyncio.ensure_future(self.keys_upload()))

                if self.should_query_keys:
                    tasks.append(asyncio.ensure_future(self.keys_query()))

                if self.should_claim_keys:
                    tasks.append(
                        asyncio.ensure_future(
                            self.keys_claim(self.get_users_for_key_claiming()),
                        )
                    )

                for response in asyncio.as_completed(tasks):
                    await self.run_response_callbacks([await response])

                # CHANGE: Run IPC callback.
                await self._run_ipc_callback()

                first_sync = False
                full_state = None
                since = None

                self.synced.set()
                self.synced.clear()

                if loop_sleep_time:
                    await asyncio.sleep(loop_sleep_time / 1000)

            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()

                break

    def set_ipc_callback(self, func: Coroutine) -> None:
        """Add a coroutine that will be called if there are any items in the IPC queue."""
        self._ipc_callback = func

    async def _run_ipc_callback(self) -> None:
        """Run the configured IPC callback."""
        while not self._ipc_queue.empty():
            payload = await self._ipc_queue.get()
            asyncio.create_task(self._ipc_callback(payload))
            self._ipc_queue.task_done()
