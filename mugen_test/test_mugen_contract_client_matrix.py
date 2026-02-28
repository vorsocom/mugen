"""Unit tests for core Matrix client contract defaults."""

import unittest

from mugen.core.contract.client.matrix import IMatrixClient


class _MatrixClientPort(IMatrixClient):
    synced = object()

    async def __aenter__(self) -> "_MatrixClientPort":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        _ = (exc_type, exc_val, exc_tb)
        return False

    @property
    def sync_token(self) -> str:
        return "token"

    async def cleanup_known_user_devices_list(self) -> None:
        return None

    async def trust_known_user_devices(self) -> None:
        return None

    async def verify_user_devices(self, user_id: str) -> None:
        _ = user_id
        return None


class TestMugenContractClientMatrix(unittest.IsolatedAsyncioTestCase):
    """Validate default method stubs on IMatrixClient."""

    async def test_default_methods_raise_not_implemented(self) -> None:
        client = _MatrixClientPort()

        with self.assertRaises(NotImplementedError):
            await client.sync_forever()
        with self.assertRaises(NotImplementedError):
            await client.get_profile()
        with self.assertRaises(NotImplementedError):
            await client.set_displayname()
