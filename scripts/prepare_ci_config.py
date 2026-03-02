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
        default="ci-quart-secret-key",
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


def _enable_web_framework_plugin(doc: tomlkit.TOMLDocument) -> None:
    plugins = doc["mugen"]["modules"]["core"]["plugins"]
    for plugin in plugins:
        if (
            str(plugin.get("type", "")).strip().lower() == "fw"
            and str(plugin.get("token", "")).strip().lower()
            == _WEB_FRAMEWORK_PLUGIN_TOKEN
        ):
            plugin["enabled"] = True
            return


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
        _enable_web_framework_plugin(doc)
        doc["web"]["media"]["storage"]["path"] = args.web_media_storage_path
        doc["web"]["media"]["object"]["cache_path"] = (
            args.web_media_object_cache_path
        )

    output_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
