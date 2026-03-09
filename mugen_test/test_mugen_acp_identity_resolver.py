"""Unit tests for mugen.core.plugin.acp.utility.identity."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.core.plugin.acp.utility.identity import (
    ACP_FRAMEWORK_TOKEN,
    resolve_acp_admin_namespace,
    resolve_acp_identity,
)


def _fw_entry(
    *,
    token: str = ACP_FRAMEWORK_TOKEN,
    namespace: str = "com.vorsocomputing.mugen.acp",
    name: str = "com.vorsocomputing.mugen.acp",
    contrib: str = "mugen.core.plugin.acp.contrib",
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "type": "fw",
        "token": token,
        "enabled": enabled,
        "name": name,
        "namespace": namespace,
        "contrib": contrib,
    }


def _dict_cfg(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "mugen": {
            "modules": {
                "extensions": list(entries),
            }
        }
    }


def _namespace_cfg(*entries: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            modules=SimpleNamespace(
                extensions=list(entries),
            )
        )
    )


class TestMugenAcpIdentityResolver(unittest.TestCase):
    """Covers ACP identity discovery from unified extension config."""

    def test_resolve_identity_from_dict_config(self) -> None:
        identity = resolve_acp_identity(
            _dict_cfg(_fw_entry(namespace=" ACP.Namespace "))
        )

        self.assertEqual(identity.token, ACP_FRAMEWORK_TOKEN)
        self.assertEqual(identity.namespace, "ACP.Namespace")
        self.assertEqual(identity.name, "com.vorsocomputing.mugen.acp")
        self.assertEqual(identity.contrib, "mugen.core.plugin.acp.contrib")

    def test_resolve_identity_from_namespace_config(self) -> None:
        identity = resolve_acp_identity(
            _namespace_cfg(
                SimpleNamespace(
                    type="fw",
                    token=ACP_FRAMEWORK_TOKEN,
                    namespace=" Com.Test.Admin ",
                    name="custom.acp",
                    contrib="custom.contrib",
                )
            )
        )

        self.assertEqual(identity.namespace, "Com.Test.Admin")
        self.assertEqual(identity.name, "custom.acp")
        self.assertEqual(identity.contrib, "custom.contrib")
        self.assertEqual(
            resolve_acp_admin_namespace(
                _namespace_cfg(
                    SimpleNamespace(
                        type="fw",
                        token=ACP_FRAMEWORK_TOKEN,
                        namespace=" Com.Test.Admin ",
                    )
                )
            ),
            "Com.Test.Admin",
        )

    def test_resolve_identity_collapses_identical_duplicates(self) -> None:
        identity = resolve_acp_identity(
            _dict_cfg(
                _fw_entry(),
                _fw_entry(),
            )
        )

        self.assertEqual(identity.namespace, "com.vorsocomputing.mugen.acp")

    def test_resolve_identity_rejects_conflicting_duplicates(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "conflicting mugen.modules.extensions"
        ):
            resolve_acp_identity(
                _dict_cfg(
                    _fw_entry(namespace="com.vorsocomputing.mugen.acp"),
                    _fw_entry(namespace="com.vorsocomputing.mugen.admin"),
                )
            )

    def test_resolve_identity_requires_non_empty_namespace(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "namespace is required"):
            resolve_acp_identity(_dict_cfg(_fw_entry(namespace="   ")))

    def test_resolve_identity_requires_acp_extension(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "token 'core.fw.acp' is required"):
            resolve_acp_identity(
                _dict_cfg(
                    _fw_entry(
                        token="core.fw.audit",
                        namespace="com.vorsocomputing.mugen.audit",
                    )
                )
            )

    def test_resolve_identity_treats_null_extensions_as_empty(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "token 'core.fw.acp' is required"):
            resolve_acp_identity({"mugen": {"modules": {"extensions": None}}})

    def test_resolve_identity_rejects_non_framework_acp_entry(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must declare type='fw'"):
            resolve_acp_identity(
                _dict_cfg(
                    {
                        "type": "cp",
                        "token": ACP_FRAMEWORK_TOKEN,
                        "namespace": "com.vorsocomputing.mugen.acp",
                    }
                )
            )

    def test_resolve_identity_enabled_only_requires_enabled_acp_entry(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "enabled framework extension token 'core.fw.acp' is required",
        ):
            resolve_acp_identity(
                _dict_cfg(_fw_entry(enabled=False)),
                enabled_only=True,
            )

    def test_resolve_identity_rejects_invalid_extensions_shape(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "mugen.modules.extensions must be a list"
        ):
            resolve_acp_identity({"mugen": {"modules": {"extensions": {}}}})

        with self.assertRaisesRegex(RuntimeError, "extensions\\[0\\] must be a table"):
            resolve_acp_identity({"mugen": {"modules": {"extensions": ["bad"]}}})

    def test_resolve_identity_handles_unsupported_root_object(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "token 'core.fw.acp' is required"):
            resolve_acp_identity(object())

    def test_resolve_identity_rejects_non_string_namespace(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "namespace is required"):
            resolve_acp_identity(
                _dict_cfg(
                    {
                        "type": "fw",
                        "token": ACP_FRAMEWORK_TOKEN,
                        "namespace": 123,
                    }
                )
            )
