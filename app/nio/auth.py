"""
Provides matrix authentication functions.
"""

import sys

from nio import AsyncClient, LoginResponse

from app.contract.keyval_storage_gateway import IKeyValStorageGateway


def persist_login_details(
    resp: LoginResponse, keyval_storage_gateway: IKeyValStorageGateway
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
    client: AsyncClient, keyval_storage_gateway: IKeyValStorageGateway
) -> bool:
    """Login to matrix server."""
    if keyval_storage_gateway.get("client_access_token") is None:
        print("First time use.")
        pw = keyval_storage_gateway.get("matrix_client_password")
        dn = keyval_storage_gateway.get("matrix_client_device_name")
        resp = await client.login(pw, dn)

        # check login successful
        if isinstance(resp, LoginResponse):
            persist_login_details(resp, keyval_storage_gateway)
        else:
            print(f"homeserver = {client.homeserver}; user = {client.user_id}")
            print(f"Login failed: {resp}")
            sys.exit(1)
        print(
            "Logged in using password. Credentials stored."
            + "Next login will use credentials.",
        )

        return False

    # Otherwise the config file exists, so we'll use the stored credentials.
    print("Logging in using saved credentials.")
    # open the file in read-only mode.
    client.access_token = keyval_storage_gateway.get("client_access_token")
    client.device_id = keyval_storage_gateway.get("client_device_id")
    client.user_id = keyval_storage_gateway.get("client_user_id")
    return True
