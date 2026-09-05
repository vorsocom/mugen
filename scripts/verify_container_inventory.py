"""Fail a container build when installed Python packages drift from its lock."""

from importlib import metadata
import json
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def expected_inventory(requirements_text: str) -> dict[str, str]:
    """Read exact pins active on this interpreter from the hashed export."""
    expected = {}
    for line in requirements_text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line.removesuffix("\\").strip())
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise RuntimeError(f"Container requirement is not exactly pinned: {line}")
        expected[canonicalize_name(requirement.name)] = pins[0].version
    return expected


def verify_inventory(
    expected: dict[str, str], installed: dict[str, str], lock: dict
) -> None:
    """Compare the actual inventory to both the export and reviewed lockfile."""
    locked = {
        (canonicalize_name(package["name"]), package["version"])
        for package in lock["package"]
        if "main" in package["groups"]
    }
    for name, version in expected.items():
        if (name, version) not in locked:
            raise RuntimeError(f"Exported package is not locked: {name}=={version}")
        if installed.get(name) != version:
            raise RuntimeError(
                f"Installed package differs from lock: {name}=={version}"
            )
    # pip belongs to the Python base image; every application package must be locked.
    unexpected = installed.keys() - expected.keys() - {"pip"}
    if unexpected:
        raise RuntimeError(f"Unreviewed installed packages: {sorted(unexpected)}")
    if not expected.get("torch", "").endswith("+cpu"):
        raise RuntimeError("The container must install the locked CPU Torch build")
    if any(name.startswith(("nvidia-", "cuda-", "triton")) for name in installed):
        raise RuntimeError("Unexpected GPU runtime in the CPU container")


def main() -> None:
    """Check the live image and perform a small CPU tensor operation."""
    import torch  # pylint: disable=import-outside-toplevel

    root = Path(__file__).resolve().parents[1]
    expected = expected_inventory((root / "container-requirements.txt").read_text())
    installed = {
        canonicalize_name(distribution.metadata["Name"]): distribution.version
        for distribution in metadata.distributions()
    }
    lock = tomllib.loads((root / "poetry.lock").read_text())
    verify_inventory(expected, installed, lock)
    if torch.__version__ != installed["torch"] or torch.version.cuda is not None:
        raise RuntimeError("Imported Torch does not match the locked CPU distribution")
    if (torch.tensor([2.0, 3.0]) ** 2).sum().item() != 13.0:
        raise RuntimeError("CPU Torch smoke check failed")
    print(json.dumps({"torch": torch.__version__, "packages_verified": len(expected)}))


if __name__ == "__main__":
    main()
