"""Regression tests for non-ACP import-time DI safety."""

from pathlib import Path
import subprocess
import sys
import unittest


class TestMuGenDiRuntimeImportRegression(unittest.TestCase):
    """Ensure selected modules do not resolve DI container at import-time."""

    def test_non_acp_modules_import_without_container_resolution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        modules = [
            "mugen",
            "mugen.core.extension.cp.clear_history",
            "mugen.core.extension.mh.default_text",
            "mugen.core.plugin.context_engine.fw_ext",
            "mugen.core.plugin.context_engine.service.contributor",
            "mugen.core.plugin.whatsapp.wacapi.api.decorator",
            "mugen.core.plugin.whatsapp.wacapi.api.webhook",
            "mugen.core.plugin.whatsapp.wacapi.fw_ext",
            "mugen.core.plugin.whatsapp.wacapi.ipc_ext",
            "mugen.core.plugin.web.api.decorator",
            "mugen.core.plugin.web.api.chat",
            "mugen.core.plugin.web.contrib",
            "mugen.core.plugin.web.fw_ext",
            "mugen.core.plugin.web.model",
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
                "Module import touched DI container at import-time.\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            ),
        )
