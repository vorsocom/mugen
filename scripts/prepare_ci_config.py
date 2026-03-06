#!/usr/bin/env python3
"""Prepare mugen.toml for deterministic CI gates."""

from __future__ import annotations

import argparse
from pathlib import Path

import tomlkit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from werkzeug.security import generate_password_hash


_WEB_PLATFORM = "web"
_WEB_FRAMEWORK_PLUGIN_TOKEN = "core.fw.web"
_CI_COMPLETION_GATEWAY_TOKEN = "deterministic"
_CI_REQUIRED_FRAMEWORK_EXTENSIONS: tuple[dict[str, str], ...] = (
    {
        "token": "core.fw.acp",
        "name": "com.vorsocomputing.mugen.acp",
        "namespace": "com.vorsocomputing.mugen.acp",
        "models": "mugen.core.plugin.acp.model",
        "contrib": "mugen.core.plugin.acp.contrib",
    },
    {
        "token": "core.fw.audit",
        "name": "com.vorsocomputing.mugen.audit",
        "namespace": "com.vorsocomputing.mugen.audit",
        "models": "mugen.core.plugin.audit.model",
        "contrib": "mugen.core.plugin.audit.contrib",
    },
    {
        "token": "core.fw.ops_vpn",
        "name": "com.vorsocomputing.mugen.ops_vpn",
        "namespace": "com.vorsocomputing.mugen.ops_vpn",
        "models": "mugen.core.plugin.ops_vpn.model",
        "contrib": "mugen.core.plugin.ops_vpn.contrib",
    },
    {
        "token": "core.fw.ops_case",
        "name": "com.vorsocomputing.mugen.ops_case",
        "namespace": "com.vorsocomputing.mugen.ops_case",
        "models": "mugen.core.plugin.ops_case.model",
        "contrib": "mugen.core.plugin.ops_case.contrib",
    },
    {
        "token": "core.fw.ops_sla",
        "name": "com.vorsocomputing.mugen.ops_sla",
        "namespace": "com.vorsocomputing.mugen.ops_sla",
        "models": "mugen.core.plugin.ops_sla.model",
        "contrib": "mugen.core.plugin.ops_sla.contrib",
    },
    {
        "token": "core.fw.ops_metering",
        "name": "com.vorsocomputing.mugen.ops_metering",
        "namespace": "com.vorsocomputing.mugen.ops_metering",
        "models": "mugen.core.plugin.ops_metering.model",
        "contrib": "mugen.core.plugin.ops_metering.contrib",
    },
    {
        "token": "core.fw.ops_workflow",
        "name": "com.vorsocomputing.mugen.ops_workflow",
        "namespace": "com.vorsocomputing.mugen.ops_workflow",
        "models": "mugen.core.plugin.ops_workflow.model",
        "contrib": "mugen.core.plugin.ops_workflow.contrib",
    },
    {
        "token": "core.fw.ops_governance",
        "name": "com.vorsocomputing.mugen.ops_governance",
        "namespace": "com.vorsocomputing.mugen.ops_governance",
        "models": "mugen.core.plugin.ops_governance.model",
        "contrib": "mugen.core.plugin.ops_governance.contrib",
    },
    {
        "token": "core.fw.ops_reporting",
        "name": "com.vorsocomputing.mugen.ops_reporting",
        "namespace": "com.vorsocomputing.mugen.ops_reporting",
        "models": "mugen.core.plugin.ops_reporting.model",
        "contrib": "mugen.core.plugin.ops_reporting.contrib",
    },
    {
        "token": "core.fw.ops_connector",
        "name": "com.vorsocomputing.mugen.ops_connector",
        "namespace": "com.vorsocomputing.mugen.ops_connector",
        "models": "mugen.core.plugin.ops_connector.model",
        "contrib": "mugen.core.plugin.ops_connector.contrib",
    },
    {
        "token": "core.fw.billing",
        "name": "com.vorsocomputing.mugen.billing",
        "namespace": "com.vorsocomputing.mugen.billing",
        "models": "mugen.core.plugin.billing.model",
        "contrib": "mugen.core.plugin.billing.contrib",
    },
    {
        "token": "core.fw.knowledge_pack",
        "name": "com.vorsocomputing.mugen.knowledge_pack",
        "namespace": "com.vorsocomputing.mugen.knowledge_pack",
        "models": "mugen.core.plugin.knowledge_pack.model",
        "contrib": "mugen.core.plugin.knowledge_pack.contrib",
    },
    {
        "token": "core.fw.channel_orchestration",
        "name": "com.vorsocomputing.mugen.channel_orchestration",
        "namespace": "com.vorsocomputing.mugen.channel_orchestration",
        "models": "mugen.core.plugin.channel_orchestration.model",
        "contrib": "mugen.core.plugin.channel_orchestration.contrib",
    },
    {
        "token": "core.fw.context_engine",
        "name": "com.vorsocomputing.mugen.context_engine",
        "namespace": "com.vorsocomputing.mugen.context_engine",
        "models": "",
        "contrib": "mugen.core.plugin.context_engine.contrib",
    },
    {
        "token": "core.fw.web",
        "name": "com.vorsocomputing.mugen.web",
        "namespace": "com.vorsocomputing.mugen.web",
        "models": "mugen.core.plugin.web.model",
        "contrib": "mugen.core.plugin.web.contrib",
    },
)


def _generate_ed25519_private_pem() -> str:
    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a CI-safe mugen.toml from conf/mugen.toml.sample."
    )
    parser.add_argument(
        "--sample",
        default="conf/mugen.toml.sample",
        help="Path to sample config (default: conf/mugen.toml.sample).",
    )
    parser.add_argument(
        "--output",
        default="mugen.toml",
        help="Output config path (default: mugen.toml).",
    )
    parser.add_argument(
        "--rdbms-url",
        default="postgresql+psycopg://mugen:mugen@127.0.0.1:5432/mugen",
        help="RDBMS URL used for both alembic and sqlalchemy configs.",
    )
    parser.add_argument(
        "--aws-region",
        default="us-east-1",
        help="AWS Bedrock region for test config.",
    )
    parser.add_argument(
        "--admin-password",
        default="aDmin,123",
        help="ACP admin password used by HTTP E2E specs.",
    )
    parser.add_argument(
        "--jwt-kid",
        default="ci-ed25519",
        help="ACP JWT key id for CI.",
    )
    parser.add_argument(
        "--jwt-issuer",
        default="mugen-ci",
        help="ACP JWT issuer for CI.",
    )
    parser.add_argument(
        "--jwt-audience",
        default="mugen-ci",
        help="ACP JWT audience for CI.",
    )
    parser.add_argument(
        "--acp-secret-key",
        default="ci-acp-secret-key",
        help="ACP secret_key value for CI.",
    )
    parser.add_argument(
        "--refresh-token-pepper",
        default="ci-refresh-pepper",
        help="ACP refresh_token_pepper value for CI.",
    )
    parser.add_argument(
        "--quart-secret-key",
        default="ci-quart-secret-key-0123456789abcdef",
        help="Quart secret_key value for CI.",
    )
    parser.add_argument(
        "--web-media-storage-path",
        default=".tmp/ci/web_media",
        help="Path for web.media.storage.path when --enable-web-platform is set.",
    )
    parser.add_argument(
        "--web-media-object-cache-path",
        default=".tmp/ci/web_media_object_cache",
        help="Path for web.media.object.cache_path when --enable-web-platform is set.",
    )
    parser.add_argument(
        "--enable-web-platform",
        action="store_true",
        help=(
            "Enable web platform in generated config and set the web framework "
            "plugin enabled=true."
        ),
    )
    return parser.parse_args()


def _ensure_platform_enabled(doc: tomlkit.TOMLDocument, platform: str) -> None:
    platforms = doc["mugen"]["platforms"]
    if platform not in [str(item) for item in platforms]:
        platforms.append(platform)


def _ensure_framework_extension(
    doc: tomlkit.TOMLDocument,
    *,
    token: str,
    name: str,
    namespace: str,
    models: str,
    contrib: str,
) -> None:
    normalized_token = token.strip().lower()
    modules = doc["mugen"]["modules"]
    core_modules = modules["core"]
    if "extensions" not in core_modules or not isinstance(
        core_modules.get("extensions"), list
    ):
        core_modules["extensions"] = tomlkit.aot()
    if "extensions" not in modules or not isinstance(modules.get("extensions"), list):
        modules["extensions"] = tomlkit.aot()

    matches: list[tuple[object, int, object]] = []
    core_matches: list[tuple[object, int, object]] = []
    plugin_matches: list[tuple[object, int, object]] = []
    sections = [core_modules["extensions"], modules["extensions"]]
    for section in sections:
        for index, extension in enumerate(section):
            if (
                str(extension.get("type", "")).strip().lower() == "fw"
                and str(extension.get("token", "")).strip().lower() == normalized_token
            ):
                match = (section, index, extension)
                matches.append(match)
                if section is modules["extensions"]:
                    plugin_matches.append(match)
                else:
                    core_matches.append(match)

    if matches:
        if plugin_matches:
            _, _, extension = plugin_matches[0]
        else:
            extension = tomlkit.table()
            modules["extensions"].append(extension)
        extension["type"] = "fw"
        extension["token"] = token
        extension["enabled"] = True
        extension["name"] = name
        extension["namespace"] = namespace
        if models:
            extension["models"] = models
        elif "models" in extension:
            del extension["models"]
        extension["contrib"] = contrib

        duplicate_matches = [match for match in matches if match[2] is not extension]
        for section, index, _ in reversed(duplicate_matches):
            del section[index]
        return

    # CI requires deterministic extension metadata for migration seeding.
    extension = tomlkit.table()
    extension["type"] = "fw"
    extension["token"] = token
    extension["enabled"] = True
    extension["name"] = name
    extension["namespace"] = namespace
    if models:
        extension["models"] = models
    extension["contrib"] = contrib
    modules["extensions"].append(extension)


def _enable_ci_framework_plugins(doc: tomlkit.TOMLDocument) -> None:
    for extension in _CI_REQUIRED_FRAMEWORK_EXTENSIONS:
        _ensure_framework_extension(
            doc,
            token=extension["token"],
            name=extension["name"],
            namespace=extension["namespace"],
            models=extension["models"],
            contrib=extension["contrib"],
        )


def main() -> int:
    args = _parse_args()
    sample_path = Path(args.sample)
    output_path = Path(args.output)

    doc = tomlkit.parse(sample_path.read_text(encoding="utf-8"))

    doc["aws"]["bedrock"]["api"]["region"] = args.aws_region
    doc["rdbms"]["alembic"]["url"] = args.rdbms_url
    doc["rdbms"]["sqlalchemy"]["url"] = args.rdbms_url

    # CI should use a deterministic no-network completion gateway.
    doc["mugen"]["modules"]["core"]["gateway"]["completion"] = (
        _CI_COMPLETION_GATEWAY_TOKEN
    )

    doc["quart"]["secret_key"] = args.quart_secret_key

    doc["acp"]["admin_password"] = args.admin_password
    doc["acp"]["admin_password_hash"] = generate_password_hash(args.admin_password)
    doc["acp"]["login_dummy_hash"] = generate_password_hash("ci-dummy-password")
    doc["acp"]["secret_key"] = args.acp_secret_key
    doc["acp"]["refresh_token_pepper"] = args.refresh_token_pepper

    doc["acp"]["jwt"]["active_kid"] = args.jwt_kid
    doc["acp"]["jwt"]["issuer"] = args.jwt_issuer
    doc["acp"]["jwt"]["audience"] = args.jwt_audience

    key_entry = doc["acp"]["jwt"]["keys"][0]
    key_entry["kid"] = args.jwt_kid
    key_entry["alg"] = "EdDSA"
    key_entry["pem"] = _generate_ed25519_private_pem()

    if args.enable_web_platform:
        _ensure_platform_enabled(doc, _WEB_PLATFORM)
        _enable_ci_framework_plugins(doc)
        doc["web"]["media"]["storage"]["path"] = args.web_media_storage_path
        doc["web"]["media"]["object"]["cache_path"] = (
            args.web_media_object_cache_path
        )

    output_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
