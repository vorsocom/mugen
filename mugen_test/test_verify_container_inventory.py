"""Regression checks for the final-image dependency drift gate."""

from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.verify_container_inventory import (
    expected_inventory,
    main,
    verify_inventory,
)


class TestVerifyContainerInventory(unittest.TestCase):
    """Reject hidden overrides, unlocked packages, and non-CPU Torch builds."""

    def setUp(self) -> None:
        self.expected = {"torch": "2.13.0+cpu"}
        self.installed = {**self.expected, "pip": "26.0"}
        self.lock = {
            "package": [
                {"name": "torch", "version": "2.13.0+cpu", "groups": ["main"]},
                {"name": "pytest", "version": "9.0.3", "groups": ["dev"]},
            ]
        }

    def test_export_parser_evaluates_environment_and_requires_exact_pins(self) -> None:
        self.assertEqual(
            expected_inventory(
                "\n# export\n--extra-index-url https://download.pytorch.org/whl/cpu\n"
                'Torch==2.13.0+cpu ; python_version >= "3.12" \\\n'
                "    --hash=sha256:123\n"
                'other==1 ; python_version < "3.12"\n'
            ),
            self.expected,
        )
        for text in ("torch", "torch>=2.10", "torch==2.*", "torch>=2,<3"):
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(RuntimeError, "pinned"),
            ):
                expected_inventory(text)

    def test_inventory_matches_export_and_lock(self) -> None:
        verify_inventory(self.expected, self.installed, self.lock)

    def test_rejects_the_previous_container_downgrade(self) -> None:
        self.installed["torch"] = "2.8.0+cpu"
        with self.assertRaisesRegex(RuntimeError, "differs from lock"):
            verify_inventory(self.expected, self.installed, self.lock)

    def test_rejects_export_modified_outside_lock(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not locked"):
            verify_inventory({"torch": "2.8.0+cpu"}, self.installed, self.lock)

    def test_rejects_missing_and_unreviewed_packages(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "differs from lock"):
            verify_inventory(self.expected, {}, self.lock)
        self.installed["unreviewed"] = "1"
        with self.assertRaisesRegex(RuntimeError, "Unreviewed"):
            verify_inventory(self.expected, self.installed, self.lock)

    def test_rejects_non_cpu_build_and_gpu_dependencies(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "CPU Torch"):
            verify_inventory({}, {"pip": "26.0"}, self.lock)
        self.expected["nvidia-runtime"] = "1"
        self.installed["nvidia-runtime"] = "1"
        self.lock["package"].append(
            {"name": "nvidia-runtime", "version": "1", "groups": ["main"]}
        )
        with self.assertRaisesRegex(RuntimeError, "GPU runtime"):
            verify_inventory(self.expected, self.installed, self.lock)

    def test_live_inventory_entrypoint_and_torch_runtime(self) -> None:
        torch = Mock(__version__="2.13.0+cpu", version=SimpleNamespace(cuda=None))
        torch.tensor.return_value.__pow__ = Mock(
            return_value=Mock(sum=Mock(return_value=Mock(item=Mock(return_value=13.0))))
        )
        distribution = SimpleNamespace(metadata={"Name": "Torch"}, version="2.13.0+cpu")
        lock_text = '[[package]]\nname="torch"\nversion="2.13.0+cpu"\ngroups=["main"]\n'
        with (
            patch.dict("sys.modules", {"torch": torch}),
            patch("importlib.metadata.distributions", return_value=[distribution]),
            patch.object(
                Path, "read_text", side_effect=["torch==2.13.0+cpu", lock_text] * 5
            ),
            patch("builtins.print") as output,
        ):
            main()
            output.assert_called_once_with(
                '{"torch": "2.13.0+cpu", "packages_verified": 1}'
            )
            torch.__version__ = "2.8.0+cpu"
            with self.assertRaisesRegex(RuntimeError, "Imported Torch"):
                main()
            torch.__version__ = "2.13.0+cpu"
            torch.version.cuda = "13"
            with self.assertRaisesRegex(RuntimeError, "Imported Torch"):
                main()
            torch.version.cuda = None
            torch.tensor.return_value.__pow__.return_value.sum.return_value.item.return_value = (
                0
            )
            with self.assertRaisesRegex(RuntimeError, "smoke check"):
                main()
            torch.tensor.return_value.__pow__.return_value.sum.return_value.item.return_value = (
                13.0
            )
            runpy.run_path("scripts/verify_container_inventory.py", run_name="__main__")
