<p align="center">
    <img src="assets/images/mugen-logotype.png" width="401">
</p>

# muGen: Python Framework for Multi-Channel AI Assistants and Agent Applications

[![Static Badge](https://img.shields.io/badge/License-Sustainable_Use_1.0-blue)](LICENSE.md)
[![Test Gates](https://github.com/vorsocom/mugen/actions/workflows/test-gates.yml/badge.svg?branch=develop)](https://github.com/vorsocom/mugen/actions/workflows/test-gates.yml?query=branch%3Adevelop)
[![Release Automation](https://github.com/vorsocom/mugen/actions/workflows/release.yml/badge.svg)](https://github.com/vorsocom/mugen/actions/workflows/release.yml)
[![GitHub Release](https://img.shields.io/github/v/release/vorsocom/mugen)](https://github.com/vorsocom/mugen/releases)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![Static Badge](https://img.shields.io/badge/Test_Coverage-100%25-green)

muGen (pronounced "mew-jen") is a Python framework for building multi-tenant AI assistants and agent-backed applications that run across web and messaging channels. It is designed for teams that want one runtime for chat, web, retrieval, governance, and provider integration without hard-wiring the system to a single model vendor or transport.

At its core, muGen combines a multi-channel messaging runtime, an ACP-backed control plane, a provider-neutral context engine, and an optional agent runtime for durable background work. Read on for the high-level framework story, or jump straight to the [quick start](#quick-start).

## Why muGen

- **Build one assistant runtime for multiple channels.** muGen supports web chat plus messaging platforms from the same core runtime and extension model.
- **Keep tenant control and operations in the framework.** ACP-backed resources, actions, RBAC, runtime profiles, and admin APIs make multi-tenant control-plane concerns first-class.
- **Use retrieval and context without locking into one provider.** The context engine composes contributors, guards, rankers, caches, provenance, and writeback behind typed contracts.
- **Add agent behavior without replacing the core messaging path.** Routes can opt into an agent runtime that supports planning, evaluation, capability execution, and resumable background continuation.
- **Swap infrastructure through gateways.** Completion, knowledge, email, SMS, and storage surfaces are exposed through provider-neutral contracts.
- **Get durable transport behavior.** Web delivery includes queueing and SSE replay semantics, while supported messaging platforms share durable ingress, dedupe, retries, and dead-letter handling.

## Supported Channels

Core platform support is documented in [clients](docs/clients.md), the shared [messaging ingress contract](docs/messaging-ingress-contract.md), and the platform-specific support contracts.

| Channel | Current core surface |
| --- | --- |
| Web | Authenticated REST + SSE chat transport with queueing, replay, and tokenized media delivery |
| Matrix | DM-first transport with ACP-managed client profiles and shared ingress durability |
| LINE | Webhook ingress via shared durable ingress foundation |
| Signal | Shared durable ingress with account-scoped routing |
| Telegram | Webhook ingress via shared durable ingress foundation |
| WeChat | Webhook ingress via shared durable ingress foundation |
| WhatsApp | Webhook ingress via shared durable ingress foundation |

## Supported Providers

muGen uses strict provider tokens in config and exposes provider-neutral contracts for gateway integrations. See [gateways](docs/gateways.md) and [dependency injection](docs/dependency-injection.md) for the current runtime contract.

| Gateway category | Supported providers |
| --- | --- |
| Completion | AWS Bedrock, Azure AI Foundry, Cerebras, Groq, OpenAI, SambaNova, Vertex AI |
| Knowledge | ChromaDB, Milvus, Pinecone, pgvector, Qdrant, Weaviate |
| Email | Amazon SES, SMTP |
| SMS | Twilio |

## Architecture

muGen keeps the runtime split into a small number of explicit seams so web, messaging, context, agent execution, and provider integrations can evolve independently.

- **Platforms and transport:** web uses authenticated REST + SSE contracts, while Matrix, LINE, Signal, Telegram, WeChat, and WhatsApp share one durable ingress foundation for staging, dedupe, retries, and checkpoints.
- **ACP and framework extensions:** ACP-backed plugins expose tenant-scoped CRUD, actions, RBAC, runtime profiles, and admin APIs, while framework extensions register platform and feature surfaces during bootstrap.
- **Context engine:** the core messaging path prepares one normalized completion request through provider-neutral contributors, guards, rankers, caches, trace sinks, and post-turn commit behavior.
- **Agent runtime:** routes can optionally hand prepared turns to a dedicated agent runtime for plan-act-evaluate loops, capability execution, and durable background continuation.
- **Gateways and services:** completion, knowledge, email, SMS, and storage integrations stay behind typed contracts so providers can be swapped without rewriting the application boundary.

For the deeper runtime contracts, start with [services](docs/services.md), [context engine design](docs/context-engine-design.md), [agent runtime design](docs/agent-runtime-design.md), and [extensions](docs/extensions.md).

## Quick Start

### 1. Clone the repository and copy the sample config files

```bash
~$ git clone git@github.com:vorsocom/mugen.git
~$ cd mugen
~$ cp conf/hypercorn.toml.sample hypercorn.toml
~$ cp conf/mugen.toml.sample mugen.toml
```

### 2. Configure `mugen.toml`

At minimum:

- set `mugen.modules.core.gateway.completion` to your completion provider token;
- keep `mugen.modules.core.service.context_engine = "default"` unless you are intentionally swapping the runtime implementation;
- keep `mugen.runtime.profile = "platform_full"` unless you are intentionally using a different runtime profile;
- if `web` is enabled, keep the default web/runtime framework extensions enabled, including `core.fw.acp`, `core.fw.context_engine`, and `core.fw.web`;
- if `matrix` is enabled, set `security.secrets.encryption_key`.

Provider config values are strict tokens, not Python module paths. Current completion gateways include AWS Bedrock, Azure AI Foundry, Cerebras, Groq, OpenAI, SambaNova, and Vertex AI. For provider-specific config details, see [gateways](docs/gateways.md) and [dependency injection](docs/dependency-injection.md).

### 3. Install dependencies and activate the Poetry environment

```bash
~$ poetry install
~$ poetry shell
```

### 4. Apply migrations for enabled tracks

```bash
~$ python scripts/run_migration_tracks.py upgrade head
```

### 5. Start the application

```bash
~$ hypercorn -c hypercorn.toml quartman
```

Bootstrap lifecycle:

1. **Phase A (blocking):** load extensions and register API routes.
2. **Phase B (background):** start long-running platform clients such as Matrix, WhatsApp, or web workers.

The server does not begin serving requests until Phase A completes successfully.

### 6. Optional development harness

For local development and testing, you can run the telnet harness in a separate process:

```bash
~$ python -m mugen.devtools.telnet_harness
```

Then connect locally:

```bash
~$ telnet localhost 8888
```

The telnet harness is for development and testing only and is blocked in production.

## Container Deployment Foundation

muGen can run in a container from a non-secret base config plus runtime environment
overrides. Do not bake a local `mugen.toml` into the image. The Docker context
ignores local runtime TOML files, and the default image config points at
`conf/mugen.toml.sample`.

Build the API image:

```bash
docker build -t mugen-api .
```

The image installs the CPU-only PyTorch wheel and filters CUDA/NVIDIA Torch
packages from the exported runtime requirements. ECS Fargate does not need GPU
wheels for this API image, and avoiding them keeps the build smaller and less
fragile.

Run against an existing PostgreSQL instance by supplying environment values:

```bash
cp conf/.env.example .env
docker run --rm -p 8000:8000 --env-file .env mugen-api
```

The default HTTP start command in the image is equivalent to:

```bash
python -m hypercorn --bind 0.0.0.0:${PORT:-8000} quartman
```

When `TLS_CERT_FILE` and `TLS_KEY_FILE` are set, the same entrypoint starts
Hypercorn with `--certfile` and `--keyfile` for local HTTPS testing.

The container exposes a lightweight load-balancer liveness endpoint:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The existing deeper runtime probes remain:

- `GET /api/core/health/live`
- `GET /api/core/health/ready`

### Local Compose Smoke

Use Compose for a local PostgreSQL, migration, and API smoke path:

```bash
docker compose --env-file conf/.env.example up --build
```

Run migrations as a one-off command with the same image and environment overlay:

```bash
docker compose --env-file conf/.env.example run --rm migrate
```

Re-apply the ACP seed manifest after changing enabled extensions or ACP
contributions. This uses the same deployment overlay path as migrations, so
`MUGEN_ENABLED_EXTENSIONS`, `MUGEN_EXTENSIONS_JSON`,
`MUGEN_CONFIG_OVERLAY_JSON`, and `DATABASE_URL` are honored:

```bash
docker compose --env-file conf/.env.example run --rm api \
  python -m mugen.core.plugin.acp.migration.reseed_manifest
```

For example, Knowledge Pack is part of the baseline web/admin config, but an
existing database upgraded from an older config shows its UI route only after the
reseed has applied the
`com.vorsocomputing.mugen.knowledge_pack:configurator` permission/grant data and
the user logs in again.

The Compose services use `conf/mugen.toml.sample` and inject database, Quart,
CORS, and local-only ACP/JWT values through environment variables. They do not
mount or copy local `mugen.toml`. The bundled PostgreSQL service is not published
on the host by default, so it will not conflict with a local database already
using port `5432`; the API and migration services reach it through the internal
Compose hostname `postgres`.

For local Compose, leave `ACP_ADMIN_PASSWORD_HASH` blank. The config overlay
generates a local-only hash from `ACP_ADMIN_PASSWORD`, which avoids Compose
interpolation of `$` characters inside Werkzeug hashes. Direct `docker run` and
production deployments may still supply `ACP_ADMIN_PASSWORD_HASH` through an
env/secret channel that does not rewrite `$`.

The checked-in Compose and `conf/.env.example` ACP/JWT values are development
smoke values only. When `ACP_JWT_CONFIG_JSON` is blank in development, the
config overlay generates an ephemeral local key from `ACP_JWT_ACTIVE_KID`. For
production, inject `ACP_JWT_CONFIG_JSON` as a single ECS secret containing the
full JWT keyset and active signing key.

Generic config overlays let container deployments configure any base TOML path
without editing or mounting `mugen.toml`. `MUGEN_CONFIG_OVERLAY_FILE` accepts an
editable local `.json` or `.toml` overlay, such as
`conf/mugen.overlay.example.json`; `MUGEN_CONFIG_OVERLAY_JSON` accepts an inline
JSON object suitable for ECS Secrets Manager injection. Overlay dictionaries
merge recursively, lists replace, and direct convenience variables such as
`DATABASE_URL`, `SECRET_KEY`, `LOG_LEVEL`, and ACP values are applied last.
Detailed ECS environment mapping, selected gateway credential validation, and
provider overlay examples live in
[Container deployment and runtime overlays](docs/container-deployment.md).
For an end-to-end AWS operator checklist covering VPCs, security groups, RDS,
ECR, IAM roles, ECS clusters, migration tasks, load balancing, DNS, and
troubleshooting, see
[ECS Fargate deployment runbook](docs/ecs-fargate-deployment-runbook.md).

`conf/mugen.toml.sample` enables the baseline web/admin framework extensions:
ACP, Web, Context Engine, Audit, Channel Orchestration, and Knowledge Pack.
Compose leaves `MUGEN_ENABLED_EXTENSIONS` blank by default and relies on that
base config. Set `MUGEN_ENABLED_EXTENSIONS` only for additional opt-in
extensions; the value accepts a comma-separated list of extension tokens. Any
extension already declared in the base config can be enabled by token, and
common built-ins can also be enabled from presets. For example,
`core.fw.agent_runtime` can be enabled after its `[mugen.agent_runtime]` policy
section is configured.

Compose sets `MUGEN_PLATFORMS=web` and
`MUGEN_PHASE_B_CRITICAL_PLATFORMS=web` by default. Both values are
comma-separated lists. If `MUGEN_PLATFORMS` is set without
`MUGEN_PHASE_B_CRITICAL_PLATFORMS`, phase-B critical platforms default to the
same list as `MUGEN_PLATFORMS`; set the critical value explicitly when only a
subset of active platforms should block startup/readiness.

Downstream container images can add their own Python package or source tree on
top of the base muGen image, then declare extension metadata and migration
tracks through environment JSON instead of editing `mugen.toml`:

```dockerfile
FROM mugen-api:base

COPY acme_extension ./acme_extension
COPY plugins/acme_extension ./plugins/acme_extension
RUN pip install --no-cache-dir -e .
```

Declare downstream framework extensions with `MUGEN_EXTENSIONS_JSON`:

```json
[
  {
    "type": "fw",
    "token": "acme.fw.billing",
    "enabled": true,
    "name": "com.acme.billing",
    "namespace": "com.acme.billing",
    "contrib": "acme_extension.contrib",
    "models": "acme_extension.model",
    "migration_track": "acme_extension",
    "runtime_module": "acme_extension.fw_ext",
    "runtime_class": "BillingFWExtension"
  }
]
```

Declare downstream migration tracks with `MUGEN_MIGRATION_TRACKS_JSON`:

```json
[
  {
    "name": "acme_extension",
    "enabled": true,
    "alembic_config": "plugins/acme_extension/alembic.ini",
    "schema": "acme_extension",
    "version_table": "alembic_version",
    "version_table_schema": "acme_extension",
    "model_modules": ["acme_extension.model"]
  }
]
```

Plugin-specific runtime secrets should stay plugin-owned, for example
`ACME_BILLING_CONFIG_JSON`, or use the generic config overlay for plugin-owned
sections. Downstream extensions own validation for their own secret shapes.

For local HTTPS testing, place your certificate and private key in a git-ignored
directory such as `_dev/tls`, then set `.env` values like:

```env
PORT=8000
HOST_PORT=8443
TLS_CERT_DIR=./_dev/tls
TLS_CERT_FILE=/run/mugen/tls/localdev.vorsocomputing.com.crt
TLS_KEY_FILE=/run/mugen/tls/localdev.vorsocomputing.com.key
CORS_ALLOWED_ORIGINS=https://localdev.vorsocomputing.com:8443,http://localhost:3000,http://localhost:5173
```

That serves HTTPS on the host port while the container still binds its internal
port. ECS Fargate should continue to terminate TLS at the ALB instead of mounting
certificate files into the task.

For local-only debugging, you may bind-mount your own runtime config read-only:

```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/mugen.toml:/app/mugen.toml:ro" \
  -e MUGEN_CONFIG_FILE=mugen.toml \
  --env-file .env \
  mugen-api
```

Do not use that pattern for ECS Fargate. ECS tasks should receive deployment
values through task environment variables and secrets from AWS Secrets Manager or
an equivalent secret store.

### Runtime Environment Overrides

The application and migration runner both apply the same environment overlay:

| Environment variable | Config path |
| --- | --- |
| `MUGEN_CONFIG_OVERLAY_FILE` | editable JSON/TOML config overlay file |
| `MUGEN_CONFIG_OVERLAY_JSON` | inline JSON config overlay object |
| `ENVIRONMENT` | `mugen.environment` |
| `APP_NAME` | `mugen.logger.name` |
| `LOG_LEVEL` | `mugen.logger.level` and Quart app logger level |
| `MUGEN_PLATFORMS` | `mugen.platforms` |
| `MUGEN_PHASE_B_CRITICAL_PLATFORMS` | `mugen.runtime.phase_b.critical_platforms` |
| `MUGEN_EXTENSIONS_JSON` | downstream `mugen.modules.extensions` entries |
| `MUGEN_ENABLED_EXTENSIONS` | additional predeclared or built-in extension tokens to enable |
| `MUGEN_MIGRATION_TRACKS_JSON` | downstream `rdbms.migration_tracks.plugins` entries |
| `DATABASE_URL` | `rdbms.alembic.url`, `rdbms.sqlalchemy.url` |
| `SECRET_KEY` | `quart.secret_key` |
| `CORS_ALLOWED_ORIGINS` | `acp.cors_origins` |
| `ACP_SECRET_KEY` | `acp.secret_key` |
| `ACP_SEED_ACP` | `acp.seed_acp` |
| `ACP_ADMIN_USERNAME` | `acp.admin_username` |
| `ACP_ADMIN_LOGIN_EMAIL` | `acp.admin_login_email` |
| `ACP_ADMIN_PASSWORD` | `acp.admin_password` |
| `ACP_ADMIN_PASSWORD_HASH` | `acp.admin_password_hash` |
| `ACP_MANAGED_SECRET_ENCRYPTION_KEY` | `acp.key_management.providers.managed.encryption_key` |
| `ACP_REFRESH_TOKEN_PEPPER` | `acp.refresh_token_pepper` |
| `ACP_JWT_CONFIG_JSON` | full `acp.jwt` object, including rotation keyset |
| `ACP_JWT_ACTIVE_KID` | local development fallback for `acp.jwt.active_kid` |
| `ACP_JWT_ISSUER` | local development fallback for `acp.jwt.issuer` |
| `ACP_JWT_AUDIENCE` | local development fallback for `acp.jwt.audience` |

In `ENVIRONMENT=production`, startup fails if required database URLs, Quart
secret, ACP secrets, JWT fields, ACP bootstrap admin values, non-wildcard CORS
origins, or selected gateway credentials are missing or still use sample
placeholders. Unselected provider placeholders are allowed.

### JWT Key Rotation

For ECS, store ACP JWT configuration as one AWS Secrets Manager value and inject
it into the task as `ACP_JWT_CONFIG_JSON`:

```json
{
  "active_kid": "2026-07-ed25519",
  "issuer": "mugen",
  "audience": "mugen",
  "keys": [
    {
      "kid": "2026-06-ed25519",
      "alg": "EdDSA",
      "pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    },
    {
      "kid": "2026-07-ed25519",
      "alg": "EdDSA",
      "pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    }
  ]
}
```

Rotation is deploy/restart based because the ACP JWT service loads its keystore
at startup. Use this sequence for normal rotation:

1. Deploy `[old, new]` with `active_kid` still set to `old`.
2. Deploy `[old, new]` with `active_kid` set to `new`.
3. Keep `old` configured until all refresh tokens signed by it have expired.
4. Deploy `[new]` after the refresh-token TTL plus a small clock-skew buffer.

The default ACP refresh token lifetime is 7 days. Emergency compromise response
can remove the old key immediately, but existing sessions signed by that key
will be invalidated.

The ECS deployment path is:

```text
GitHub Actions -> ECR -> ECS Fargate -> ALB -> DNS
```

Upstream production deployment is automated from `main` through
`.github/workflows/deploy-ecs.yml` after the AWS resources and GitHub
Environment variables are configured. Use the
[ECS Fargate deployment runbook](docs/ecs-fargate-deployment-runbook.md) for
first-time setup, OIDC/IAM configuration, manual recovery commands, rollback,
and downstream workflow examples.

## Read Next

- [Building muGen applications](docs/apps.md)
- [Downstream architecture conformance](docs/downstream-architecture-conformance.md)
- [Developing extensions](docs/extensions.md)
- [Container deployment and runtime overlays](docs/container-deployment.md)
- [ECS Fargate deployment runbook](docs/ecs-fargate-deployment-runbook.md)
- [Working with gateways](docs/gateways.md)
- [Web platform support contract](docs/web-support-contract.md)
- [Human handoff backend contract](docs/human-handoff-backend.md)
- [Working with services](docs/services.md)
- [ACP RBAC policy](docs/acp-rbac-policy.md)
- [Context engine design](docs/context-engine-design.md)
- [Context engine authoring](docs/context-engine-authoring.md)
- [Agent runtime design](docs/agent-runtime-design.md)
- [Agent runtime authoring](docs/agent-runtime-authoring.md)

## Release Automation

muGen includes a release automation script that mirrors the release workflow:

```bash
# On develop, prepare a release branch and run full gates.
poetry run python scripts/release.py prepare --bump patch --python "$(poetry run which python)"

# Finish release: open the release PR to main.
poetry run python scripts/release.py finish --version 0.43.3

# After the release PR is merged on main, tag it and open the develop sync PR.
# After that PR is merged, rerun publish to clean up the release branch.
poetry run python scripts/release.py publish --version 0.43.3
```

A manual GitHub Actions workflow is also available at `.github/workflows/release.yml`.

## License

muGen is [fair-code](https://faircode.io), distributed under the [**Sustainable Use License**](LICENSE.md). For proprietary enterprise licenses, please [**request one**](mailto:license@vorsocomputing.com).

## Why Source-Available?

muGen began as a closed-source project. We moved to a source-available model because many teams want public scrutiny, operational transparency, and protection against consultancy lock-in while still needing a sustainable licensing model for the framework.

## Enterprise Services

We provide enterprise support for teams building on muGen. If you need help with architecture, extensions, platform rollout, or provider integration, [get in touch](mailto:brightideas@vorsocomputing.com).
