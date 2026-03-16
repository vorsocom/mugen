"""Plugin-local Matrix management contracts."""

from mugen.core.plugin.matrix.contract.admin import (
    IMatrixDeviceAdminClient,
    IMatrixRoomAdminClient,
)

__all__ = [
    "IMatrixDeviceAdminClient",
    "IMatrixRoomAdminClient",
]
