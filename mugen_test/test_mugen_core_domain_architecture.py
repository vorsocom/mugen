"""Architecture tests for core domain boundary rules."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from mugen.core.utility.platforms import SUPPORTED_CORE_PLATFORMS


class TestCoreDomainArchitecture(unittest.TestCase):
    """Ensures core domain modules remain infrastructure-agnostic."""

    def test_domain_modules_do_not_import_infrastructure_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        domain_root = repo_root / "mugen" / "core" / "domain"
        python_files = sorted(domain_root.rglob("*.py"))

        forbidden_prefixes = (
            "mugen.core.client",
            "mugen.core.gateway",
            "mugen.core.plugin",
            "mugen.core.service",
            "mugen.core.di",
            "mugen.core.runtime",
            "migrations.schema_contract",
            "quart",
            "sqlalchemy",
        )

        violations: list[str] = []

        for file_path in python_files:
            module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(module_tree):
                module_name = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        if module_name.startswith(forbidden_prefixes):
                            violations.append(f"{file_path}: import {module_name}")
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if module_name.startswith(forbidden_prefixes):
                        violations.append(f"{file_path}: from {module_name}")

        self.assertEqual(violations, [])

    def test_runtime_adapters_use_shared_phase_b_health_use_case(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        adapter_files = {
            repo_root / "mugen" / "__init__.py": {
                "mugen.core.domain.use_case.phase_b_health",
                "mugen.core.runtime.phase_b_runtime",
            },
            repo_root / "quartman.py": {
                "mugen.core.domain.use_case.phase_b_health",
                "mugen.core.runtime.phase_b_runtime",
            },
            repo_root / "mugen" / "core" / "api" / "endpoint.py": {
                "mugen.core.domain.use_case.phase_b_health",
            },
        }

        missing_imports: list[str] = []
        for file_path, allowed_modules in adapter_files.items():
            module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
            imported = False
            for node in ast.walk(module_tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and (node.module or "") in allowed_modules
                ):
                    imported = True
                    break
            if imported is not True:
                missing_imports.append(str(file_path))

        self.assertEqual(missing_imports, [])

    def test_endpoint_imports_phase_b_platform_observability_helper(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        endpoint_path = repo_root / "mugen" / "core" / "api" / "endpoint.py"
        endpoint_source = endpoint_path.read_text(encoding="utf-8")

        self.assertIn(
            "summarize_phase_b_platform_observability",
            endpoint_source,
        )

    def test_endpoint_does_not_redeclare_phase_b_failure_helpers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        endpoint_path = repo_root / "mugen" / "core" / "api" / "endpoint.py"
        module_tree = ast.parse(endpoint_path.read_text(encoding="utf-8"))
        function_names = {
            node.name
            for node in module_tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

        self.assertNotIn("_resolve_failed_platforms", function_names)
        self.assertNotIn("_phase_b_starting_within_grace", function_names)

    def test_extension_registry_avoids_legacy_binding_fallbacks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "mugen" / "core" / "bootstrap" / "extensions.py"
        registry_source = registry_path.read_text(encoding="utf-8")

        self.assertNotIn("register_ipc_extension", registry_source)
        self.assertNotIn("register_cp_extension", registry_source)
        self.assertNotIn("register_ct_extension", registry_source)
        self.assertNotIn("register_ctx_extension", registry_source)
        self.assertNotIn("register_mh_extension", registry_source)
        self.assertNotIn("register_rag_extension", registry_source)
        self.assertNotIn("register_rpp_extension", registry_source)
        self.assertNotIn('f"bind_{extension_type}_extension"', registry_source)

    def test_service_contracts_expose_extension_bind_operations(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        ipc_contract = repo_root / "mugen" / "core" / "contract" / "service" / "ipc.py"
        messaging_contract = (
            repo_root / "mugen" / "core" / "contract" / "service" / "messaging.py"
        )

        ipc_tree = ast.parse(ipc_contract.read_text(encoding="utf-8"))
        messaging_tree = ast.parse(messaging_contract.read_text(encoding="utf-8"))

        ipc_function_names = {
            node.name
            for node in ast.walk(ipc_tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        messaging_function_names = {
            node.name
            for node in ast.walk(messaging_tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }

        self.assertIn("bind_ipc_extension", ipc_function_names)
        self.assertIn("bind_cp_extension", messaging_function_names)
        self.assertIn("bind_ct_extension", messaging_function_names)
        self.assertIn("bind_ctx_extension", messaging_function_names)
        self.assertIn("bind_mh_extension", messaging_function_names)
        self.assertIn("bind_rag_extension", messaging_function_names)
        self.assertIn("bind_rpp_extension", messaging_function_names)

    def test_core_platform_allow_list_excludes_telnet(self) -> None:
        self.assertEqual(set(SUPPORTED_CORE_PLATFORMS), {"matrix", "web", "whatsapp"})
        self.assertNotIn("telnet", SUPPORTED_CORE_PLATFORMS)

    def test_core_runtime_bootstrap_does_not_import_dev_telnet_harness(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        runtime_path = repo_root / "mugen" / "__init__.py"
        module_tree = ast.parse(runtime_path.read_text(encoding="utf-8"))
        forbidden_imports = {
            "mugen.devtools",
            "mugen.devtools.telnet_harness",
            "mugen.core.client.telnet",
            "mugen.core.contract.client.telnet",
        }

        violations: list[str] = []
        for node in ast.walk(module_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_imports:
                        violations.append(alias.name)
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name in forbidden_imports:
                    violations.append(module_name)

        self.assertEqual(violations, [])

    def test_removed_clean_contract_files_stay_deleted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        removed_paths = [
            repo_root / "mugen" / "core" / "contract" / "clean" / "request.py",
            repo_root / "mugen" / "core" / "contract" / "clean" / "request_handler.py",
            repo_root / "mugen" / "core" / "contract" / "clean" / "response.py",
        ]
        for removed_path in removed_paths:
            self.assertFalse(removed_path.exists(), str(removed_path))

    def test_contract_layer_does_not_import_vendor_runtime_sdks(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_root = repo_root / "mugen" / "core" / "contract"
        forbidden_prefixes = (
            "quart",
            "sqlalchemy",
            "nio",
            "aiohttp",
            "boto3",
            "openai",
            "pycurl",
        )

        violations: list[str] = []
        for file_path in sorted(contract_root.rglob("*.py")):
            module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(module_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(forbidden_prefixes):
                            violations.append(f"{file_path}: import {alias.name}")
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if module_name.startswith(forbidden_prefixes):
                        violations.append(f"{file_path}: from {module_name}")

        self.assertEqual(violations, [])

    def test_client_layer_does_not_import_sqlalchemy_directly(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        client_root = repo_root / "mugen" / "core" / "client"
        violations: list[str] = []

        for file_path in sorted(client_root.rglob("*.py")):
            module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(module_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("sqlalchemy"):
                            violations.append(f"{file_path}: import {alias.name}")
                if isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if module_name.startswith("sqlalchemy"):
                        violations.append(f"{file_path}: from {module_name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
