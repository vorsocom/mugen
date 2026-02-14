"""Smoke tests for plugin model repr implementations."""

from __future__ import annotations

import enum
import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

import mugen.core.plugin as plugin_pkg


class _ReprProxy(SimpleNamespace):
    def __getattr__(self, _name: str):
        return None


class TestMugenPluginModelReprSmoke(unittest.TestCase):
    """Executes model __repr__ methods without requiring ORM instantiation."""

    def test_model_repr_methods_return_strings(self) -> None:
        root = Path(next(iter(plugin_pkg.__path__)))
        model_files = sorted(
            path
            for path in root.rglob("model/*.py")
            if path.name != "__init__.py"
        )
        self.assertGreater(len(model_files), 0)

        proxy = _ReprProxy(id=uuid.UUID(int=0))
        repr_count = 0

        for module_path in model_files:
            relative_module = module_path.relative_to(root).with_suffix("")
            module_name = "mugen.core.plugin." + ".".join(relative_module.parts)
            module = importlib.import_module(module_name)

            for exported_name in getattr(module, "__all__", []):
                exported = getattr(module, exported_name, None)
                if not inspect.isclass(exported):
                    continue
                if exported.__module__ != module.__name__:
                    continue
                if issubclass(exported, enum.Enum):
                    continue
                if "__repr__" not in exported.__dict__:
                    continue

                rendered = exported.__repr__(proxy)
                self.assertIsInstance(rendered, str)
                self.assertIn(exported.__name__, rendered)
                repr_count += 1

        self.assertGreater(repr_count, 0)
