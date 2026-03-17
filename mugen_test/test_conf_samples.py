"""Regression coverage for user-facing sample configuration files."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

import tomlkit

import mugen.core.di.provider_registry as provider_registry
from mugen.core.plugin.token_registry import get_plugin_extension_token_registry


def _load_toml(path: str):
    return tomlkit.parse(Path(path).read_text(encoding="utf-8"))


class TestConfSamples(unittest.TestCase):
    """Keep sample configuration files aligned with current expectations."""

    def test_downstream_sample_tracks_main_without_pinned_tag(self) -> None:
        doc = _load_toml("conf/downstream.toml.sample")

        self.assertEqual(doc["upstream"]["branch"], "main")
        self.assertNotIn("sync_tag", doc["upstream"])

    def test_mugen_sample_includes_message_history_defaults(self) -> None:
        doc = _load_toml("conf/mugen.toml.sample")

        messaging = doc["mugen"]["messaging"]
        self.assertEqual(messaging["history_max_messages"], 40)
        self.assertEqual(messaging["history_save_cas_retries"], 5)

    def test_mugen_sample_defaults_completion_gateway_to_deterministic(self) -> None:
        doc = _load_toml("conf/mugen.toml.sample")

        gateway = doc["mugen"]["modules"]["core"]["gateway"]
        self.assertEqual(gateway["completion"], "deterministic")

    def test_mugen_sample_model_bearing_web_fw_entries_declare_track_metadata(
        self,
    ) -> None:
        doc = _load_toml("conf/mugen.toml.sample")
        extensions = doc["mugen"]["modules"]["extensions"]
        by_token = {entry["token"]: entry for entry in extensions}

        self.assertEqual(
            by_token["core.fw.acp"]["models"],
            "mugen.core.plugin.acp.model",
        )
        self.assertEqual(by_token["core.fw.acp"]["migration_track"], "core")
        self.assertEqual(
            by_token["core.fw.web"]["models"],
            "mugen.core.plugin.web.model",
        )
        self.assertEqual(by_token["core.fw.web"]["migration_track"], "core")

    def test_mugen_sample_mentions_all_shipped_core_extension_tokens(self) -> None:
        sample_text = Path("conf/mugen.toml.sample").read_text(encoding="utf-8")
        sample_tokens = set(
            re.findall(r'^\s*#?\s*token = "([^"]+)"', sample_text, flags=re.MULTILINE)
        )
        registry_tokens = set(get_plugin_extension_token_registry())

        self.assertFalse(
            registry_tokens - sample_tokens,
            msg=f"Sample is missing core extension token(s): {sorted(registry_tokens - sample_tokens)}",
        )

    def test_mugen_sample_mentions_all_completion_provider_tokens(self) -> None:
        sample_text = Path("conf/mugen.toml.sample").read_text(encoding="utf-8")
        gateway_match = re.search(
            r"^\[mugen\.modules\.core\.gateway\]\n(?P<body>.*?)(?:^\[|\Z)",
            sample_text,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(gateway_match)
        gateway_body = gateway_match.group("body")
        sample_tokens = set(
            re.findall(
                r'^\s*#?\s*completion = "([^"]+)"',
                gateway_body,
                flags=re.MULTILINE,
            )
        )
        registry_tokens = set(provider_registry._PROVIDER_TOKEN_REGISTRY["completion_gateway"])

        self.assertFalse(
            registry_tokens - sample_tokens,
            msg=(
                "Sample is missing completion provider token(s): "
                f"{sorted(registry_tokens - sample_tokens)}"
            ),
        )
