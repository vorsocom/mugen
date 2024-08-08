"""
Provides matrix authentication functions.
"""

import sys

from nio import AsyncClient, LoginResponse

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


def persist_login_details(
    resp: LoginResponse,
    keyval_storage_gateway: IKeyValStorageGateway,
) -> None:
    """Persists login details using dbm.

    Arguments:
        resp {LoginResponse} -- the successful client login response.
        storage {_gdbm} -- a _gdbm object.
    """
    keyval_storage_gateway.put("client_access_token", resp.access_token)
    keyval_storage_gateway.put("client_device_id", resp.device_id)
    keyval_storage_gateway.put("client_user_id", resp.user_id)


async def login(
    logging_gateway: ILoggingGateway,
    client: AsyncClient,
    keyval_storage_gateway: IKeyValStorageGateway,
) -> bool:
    """Login to matrix server."""
    if keyval_storage_gateway.get("client_access_token") is None:
        logging_gateway.info("auth: First time use.")
        pw = keyval_storage_gateway.get("matrix_client_password")
        dn = keyval_storage_gateway.get("matrix_client_device_name")
        logging_gateway.info("auth: Attempting login using password.")
        resp = await client.login(pw, dn)

        # check login successful
        if isinstance(resp, LoginResponse):
            logging_gateway.info("auth: Login attempt using password successful.")
            logging_gateway.info("auth: Persisting login credentials.")
            persist_login_details(resp, keyval_storage_gateway)
        else:
            logging_gateway.info(
                f"homeserver = {client.homeserver}; user = {client.user_id}"
            )
            logging_gateway.info(f"Login attempt using password failed: {resp}")
            sys.exit(1)

        logging_gateway.info("auth: Next login will use persisted credentials.")
        return False

    # Otherwise the config file exists, so we'll use the stored credentials.
    logging_gateway.info("auth: Logging in using saved credentials.")
    # open the file in read-only mode.
    client.access_token = keyval_storage_gateway.get("client_access_token")
    client.device_id = keyval_storage_gateway.get("client_device_id")
    client.user_id = keyval_storage_gateway.get("client_user_id")
    return True
