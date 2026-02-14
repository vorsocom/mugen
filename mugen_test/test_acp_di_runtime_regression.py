"""Regression tests for ACP DI runtime resolution and AdminNs key usage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
import uuid

from mugen.core.plugin.acp.api.decorator import auth as auth_decorator
from mugen.core.plugin.acp.service.authorization import AuthorizationService
from mugen.core.plugin.acp.service.user import UserService


class _FakeUserService:
    """Minimal user service used by auth decorator tests."""

    def __init__(self, user: SimpleNamespace) -> None:
        self._user = user

    async def get(self, _where: dict) -> SimpleNamespace:
        return self._user

    async def get_expanded(self, _where: dict) -> SimpleNamespace:
        return self._user


class _FakeRegistry:
    """Registry test double that records requested service keys."""

    def __init__(self, user_svc: _FakeUserService | None = None) -> None:
        self._user_svc = user_svc
        self.requested_keys: list[str] = []

    def get_edm_service(self, key: str):
        self.requested_keys.append(key)
        if self._user_svc is not None:
            return self._user_svc
        return object()


class _FakeRegistryWithTypeLookup:
    """Registry double for `get_resource_by_type` key lookup assertions."""

    def __init__(self) -> None:
        self.resource_type_lookups: list[str] = []
        self.service_key_lookups: list[str] = []

    def get_resource_by_type(self, edm_type_name: str):
        self.resource_type_lookups.append(edm_type_name)
        return SimpleNamespace(service_key=f"svc:{edm_type_name}")

    def get_edm_service(self, service_key: str):
        self.service_key_lookups.append(service_key)
        return object()


class TestACPDiRuntimeRegression(unittest.IsolatedAsyncioTestCase):
    """Lock runtime DI behavior for ACP modules and auth code paths."""

    def test_acp_module_imports_do_not_access_di_container(self) -> None:
        root = Path(__file__).resolve().parents[1]
        modules = [
            "mugen.core.plugin.acp.api.action",
            "mugen.core.plugin.acp.api.audit",
            "mugen.core.plugin.acp.api.crud",
            "mugen.core.plugin.acp.api.decorator.auth",
            "mugen.core.plugin.acp.api.decorator.rgql",
            "mugen.core.plugin.acp.api.func_auth",
            "mugen.core.plugin.acp.api.func_ipc",
            "mugen.core.plugin.acp.fw_ext",
            "mugen.core.plugin.acp.service.authorization",
            "mugen.core.plugin.acp.service.jwt_eddsa",
            "mugen.core.plugin.acp.service.refresh_token",
            "mugen.core.plugin.acp.service.user",
        ]
        script = "\n".join(
            [
                "import importlib",
                "import mugen.core.di as di",
                "class _TrapContainer:",
                "    def __getattr__(self, name):",
                "        raise RuntimeError(",
                "            f'Import-time DI container access is forbidden: {name}'",
                "        )",
                "di.container = _TrapContainer()",
                f"modules = {modules!r}",
                "for module_name in modules:",
                "    importlib.import_module(module_name)",
            ]
        )

        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=(
                "ACP module import touched DI container at import-time.\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            ),
        )

    async def test_require_user_from_token_uses_admin_ns_user_service_key(self) -> None:
        user_id = uuid.uuid4()
        token_version = 9
        user = SimpleNamespace(
            id=user_id,
            deleted_at=None,
            locked_at=None,
            token_version=token_version,
            global_roles=[],
        )
        user_svc = _FakeUserService(user)
        registry = _FakeRegistry(user_svc=user_svc)
        config = SimpleNamespace(acp=SimpleNamespace(namespace=" Com.Test.Admin "))
        logger = SimpleNamespace(debug=lambda *_: None, error=lambda *_: None)

        result = await auth_decorator._require_user_from_token(
            {"sub": str(user_id), "token_version": token_version},
            expanded=False,
            config_provider=lambda: config,
            logger_provider=lambda: logger,
            registry_provider=lambda: registry,
        )

        self.assertIs(result, user)
        self.assertEqual(registry.requested_keys, ["com.test.admin:ACP.User"])

    def test_authorization_service_uses_admin_ns_for_edm_service_keys(self) -> None:
        registry = _FakeRegistry()
        config = SimpleNamespace(acp=SimpleNamespace(namespace=" Com.Test.Admin "))

        AuthorizationService(
            config_provider=lambda: config,
            registry_provider=lambda: registry,
        )

        self.assertEqual(
            registry.requested_keys,
            [
                "com.test.admin:ACP.GlobalPermissionEntry",
                "com.test.admin:ACP.GlobalRoleMembership",
                "com.test.admin:ACP.PermissionEntry",
                "com.test.admin:ACP.PermissionObject",
                "com.test.admin:ACP.PermissionType",
                "com.test.admin:ACP.RoleMembership",
                "com.test.admin:ACP.User",
            ],
        )

    def test_user_service_uses_expected_acp_edm_type_names(self) -> None:
        registry = _FakeRegistryWithTypeLookup()

        UserService(
            table="users",
            rsg=SimpleNamespace(),
            config_provider=lambda: SimpleNamespace(),
            logger_provider=lambda: SimpleNamespace(),
            registry_provider=lambda: registry,
        )

        self.assertEqual(
            registry.resource_type_lookups,
            [
                "ACP.User",
                "ACP.GlobalRole",
                "ACP.GlobalRoleMembership",
                "ACP.Person",
                "ACP.RefreshToken",
            ],
        )
