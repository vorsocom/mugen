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

    async def sync_forever(
        self,
        *,
        since: str | None = None,
        timeout: int = 100,
        full_state: bool = True,
        set_presence: str = "online",
    ):
        return (since, timeout, full_state, set_presence)

    async def get_profile(self, user_id: str | None = None):
        return {"user_id": user_id}

    async def set_displayname(self, displayname: str):
        return {"displayname": displayname}


class _IncompleteMatrixClientPort(IMatrixClient):
    synced = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
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

    async def test_required_matrix_methods_are_callable_on_complete_port(self) -> None:
        client = _MatrixClientPort()

        self.assertEqual(await client.sync_forever(), (None, 100, True, "online"))
        self.assertEqual(await client.get_profile(), {"user_id": None})
        self.assertEqual(await client.set_displayname("muGen"), {"displayname": "muGen"})

    async def test_incomplete_port_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteMatrixClientPort()
