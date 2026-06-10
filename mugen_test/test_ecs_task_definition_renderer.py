"""Tests for ECS deployment automation helpers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ACTION_DIR = _REPO_ROOT / ".github" / "actions" / "ecs-deploy"
_RENDERER_PATH = _ACTION_DIR / "render_task_definition.py"
_HELPER_PATH = _ACTION_DIR / "ecs_task_helpers.py"


class TestEcsTaskDefinitionRenderer(unittest.TestCase):
    """Covers placeholder rendering and template failure modes."""

    def test_valid_replacement_preserves_sidecar_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            template = tmp / "task.json"
            output = tmp / "rendered.json"
            template.write_text(
                json.dumps(
                    {
                        "containerDefinitions": [
                            {
                                "name": "mugen-api",
                                "image": "{{IMAGE_URI}}",
                                "environment": [
                                    {
                                        "name": "CORS_ALLOWED_ORIGINS",
                                        "value": "{{CORS_ALLOWED_ORIGINS}}",
                                    }
                                ],
                            },
                            {
                                "name": "sidecar",
                                "image": "public.ecr.aws/example/sidecar:stable",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(_RENDERER_PATH),
                    "--template",
                    str(template),
                    "--output",
                    str(output),
                    "--set",
                    (
                        "IMAGE_URI=123456789012.dkr.ecr.us-east-1."
                        "amazonaws.com/mugen-api:abc123"
                    ),
                    "--set",
                    "CORS_ALLOWED_ORIGINS=https://app.example.com",
                ],
                check=True,
            )

            rendered = json.loads(output.read_text(encoding="utf-8"))
            containers = rendered["containerDefinitions"]
            self.assertEqual(
                containers[0]["image"],
                "123456789012.dkr.ecr.us-east-1.amazonaws.com/mugen-api:abc123",
            )
            self.assertEqual(
                containers[0]["environment"][0]["value"],
                "https://app.example.com",
            )
            self.assertEqual(
                containers[1]["image"],
                "public.ecr.aws/example/sidecar:stable",
            )

    def test_missing_placeholder_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            template = tmp / "task.json"
            output = tmp / "rendered.json"
            template.write_text(
                '{"containerDefinitions":[{"image":"{{IMAGE_URI}}"}]}',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(_RENDERER_PATH),
                    "--template",
                    str(template),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                check=False,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing placeholder value: IMAGE_URI",
                result.stderr,
            )

    def test_custom_downstream_placeholder_is_supported_by_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            template = tmp / "task.json"
            output = tmp / "rendered.json"
            extra = tmp / "extra.json"
            template.write_text(
                json.dumps(
                    {
                        "containerDefinitions": [
                            {
                                "name": "{{DOWNSTREAM_CONTAINER_NAME}}",
                                "image": "{{IMAGE_URI}}",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            extra.write_text(
                json.dumps({"DOWNSTREAM_CONTAINER_NAME": "acme-api"}),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(_RENDERER_PATH),
                    "--template",
                    str(template),
                    "--output",
                    str(output),
                    "--extra-json",
                    str(extra),
                    "--set",
                    "IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/acme:1",
                ],
                check=True,
            )

            rendered = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                rendered["containerDefinitions"][0]["name"],
                "acme-api",
            )

    def test_invalid_extra_json_shape_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            template = tmp / "task.json"
            output = tmp / "rendered.json"
            extra = tmp / "extra.json"
            template.write_text("{}", encoding="utf-8")
            extra.write_text("[]", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(_RENDERER_PATH),
                    "--template",
                    str(template),
                    "--output",
                    str(output),
                    "--extra-json",
                    str(extra),
                ],
                capture_output=True,
                check=False,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "extra placeholders JSON must be an object",
                result.stderr,
            )

    def test_env_prefix_placeholder_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            template = tmp / "task.json"
            output = tmp / "rendered.json"
            template.write_text(
                '{"family":"{{FAMILY}}"}',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(_RENDERER_PATH),
                    "--template",
                    str(template),
                    "--output",
                    str(output),
                    "--env-prefix",
                    "TASKDEF_",
                ],
                check=True,
                env={"TASKDEF_FAMILY": "mugen-api"},
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["family"],
                "mugen-api",
            )


class TestEcsTaskHelpers(unittest.TestCase):
    """Covers non-AWS helper behavior used by the composite action."""

    def test_builds_migration_overrides(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(_HELPER_PATH),
                "overrides",
                "--container-name",
                "mugen-api",
                "--command-json",
                '["python","scripts/run_migration_tracks.py","upgrade","head"]',
            ],
            capture_output=True,
            check=True,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "containerOverrides": [
                    {
                        "name": "mugen-api",
                        "command": [
                            "python",
                            "scripts/run_migration_tracks.py",
                            "upgrade",
                            "head",
                        ],
                    }
                ]
            },
        )

    def test_run_task_failures_fail_clearly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_HELPER_PATH), "task-arn"],
            capture_output=True,
            input=json.dumps(
                {
                    "failures": [
                        {
                            "arn": "task-def/mugen-api",
                            "reason": "ACCESS_DENIED",
                        }
                    ]
                }
            ),
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("ECS run-task returned failures", result.stderr)
        self.assertIn("ACCESS_DENIED", result.stderr)

    def test_container_exit_zero_accepts_success(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(_HELPER_PATH),
                "assert-container-exit-zero",
                "--container-name",
                "mugen-api",
            ],
            capture_output=True,
            input=json.dumps(
                {
                    "tasks": [
                        {
                            "containers": [
                                {
                                    "name": "mugen-api",
                                    "exitCode": 0,
                                }
                            ]
                        }
                    ]
                }
            ),
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0)

