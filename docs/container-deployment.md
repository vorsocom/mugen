# Container Deployment And Runtime Overlays

Status: Draft
Last Updated: 2026-06-09
Audience: Operators, downstream application teams, and deployment engineers

## Purpose

This guide documents how to run the muGen API from a container without copying
local `mugen.toml` into the image or ECS task. The container starts from the
non-secret base config in `conf/mugen.toml.sample`, then applies runtime
overlays from environment variables and secret injection.

The local `mugen.toml` file is operator-owned runtime state. Do not bake it into
the image, mount it into ECS, or regenerate it from the sample file.

For a complete AWS operator checklist covering VPCs, security groups, RDS,
ECR, ECS clusters, task definitions, migration tasks, load balancing, DNS, and
debug commands, see [ECS Fargate deployment runbook](ecs-fargate-deployment-runbook.md).

## Runtime Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Builds the API image and installs runtime dependencies. |
| `compose.yaml` | Local Postgres, migration, and API smoke environment. |
| `conf/mugen.toml.sample` | Non-secret structural base config. |
| `conf/.env.example` | Local container environment example. |
| `conf/mugen.overlay.example.json` | Editable local overlay example. |
| `scripts/container_start.sh` | Hypercorn startup with optional local TLS. |

Local `.env`, `.env.*`, `mugen.toml`, and `mugen.*.toml` are ignored. The only
checked-in env file is `conf/.env.example`.

## Overlay Order

The app and migration runner apply the same resolved config flow:

1. Load base config from `MUGEN_CONFIG_FILE`.
2. Apply `MUGEN_CONFIG_OVERLAY_FILE` when set.
3. Apply `MUGEN_CONFIG_OVERLAY_JSON` when set.
4. Apply structural overlays for platforms, extensions, and migration tracks.
5. Apply direct convenience env vars last.
6. In production, validate the resolved config.

Object overlays merge recursively. Lists replace. The dedicated extension and
migration overlays keep their merge behavior:

- `MUGEN_EXTENSIONS_JSON` merges by normalized extension `token`.
- `MUGEN_MIGRATION_TRACKS_JSON` merges by migration track `name`.
- `MUGEN_ENABLED_EXTENSIONS` enables a declared or built-in extension by token.

Direct env vars intentionally win over generic overlays. For example, if
`MUGEN_CONFIG_OVERLAY_JSON` sets `rdbms.sqlalchemy.url` but `DATABASE_URL` is
also set, `DATABASE_URL` wins for both Alembic and SQLAlchemy URLs.

## Local Commands

Build the image:

```bash
docker build -t mugen-api .
```

Run the local Compose smoke path:

```bash
docker compose --env-file conf/.env.example up --build
curl http://localhost:8000/health
docker compose --env-file conf/.env.example run --rm migrate
docker compose --env-file conf/.env.example down
```

If the current shell does not include the `docker` group yet, either start a new
login session or run the command under the group:

```bash
sg docker -c 'docker compose --env-file conf/.env.example up --build'
```

Restarting the Docker daemon does not grant the current shell new group
membership.

## ECS Task Configuration

Use the same image for the long-running API service and one-off migration task.

API command:

```bash
sh scripts/container_start.sh
```

Migration command:

```bash
python scripts/run_migration_tracks.py upgrade head
```

Recommended non-secret ECS environment variables:

| Variable | Example |
| --- | --- |
| `MUGEN_CONFIG_FILE` | `conf/mugen.toml.sample` |
| `ENVIRONMENT` | `production` |
| `APP_NAME` | `mugen-api` |
| `PORT` | `8000` |
| `LOG_LEVEL` | `INFO` |
| `MUGEN_PLATFORMS` | `web` |
| `MUGEN_PHASE_B_CRITICAL_PLATFORMS` | `web` |
| `MUGEN_ENABLED_EXTENSIONS` | `core.fw.channel_orchestration,core.fw.audit` |

Recommended ECS secrets:

| Variable | Secret contents |
| --- | --- |
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL. |
| `SECRET_KEY` | Quart secret key, at least 32 chars. |
| `ACP_SECRET_KEY` | ACP bootstrap secret. |
| `ACP_MANAGED_SECRET_ENCRYPTION_KEY` | ACP managed secret root key. |
| `ACP_REFRESH_TOKEN_PEPPER` | Refresh/invitation token pepper. |
| `ACP_ADMIN_PASSWORD` | Bootstrap admin plaintext, if seeding ACP. |
| `ACP_ADMIN_PASSWORD_HASH` | Matching Werkzeug hash, if seeding ACP in production. |
| `ACP_JWT_CONFIG_JSON` | Full ACP JWT keyset and active signing key. |
| `MUGEN_CONFIG_OVERLAY_JSON` | Provider and gateway config overlay. |
| `MUGEN_EXTENSIONS_JSON` | Downstream extension metadata when sensitive or environment-specific. |
| `MUGEN_MIGRATION_TRACKS_JSON` | Downstream migration tracks when environment-specific. |

Avoid `MUGEN_CONFIG_OVERLAY_FILE` in ECS unless the file is intentionally
delivered by a secure mount. ECS tasks should normally use
`MUGEN_CONFIG_OVERLAY_JSON`.

TLS should terminate at the ALB in ECS. `TLS_CERT_FILE` and `TLS_KEY_FILE` are
for local HTTPS testing only.

## Production Validation

Production validation always checks core runtime requirements:

- `rdbms.alembic.url`
- `rdbms.sqlalchemy.url`
- `quart.secret_key`
- ACP secrets, JWT config, bootstrap admin fields, and CORS when ACP is enabled

It also validates selected gateway credentials. Unselected provider placeholders
are allowed so the sample config can remain broad without forcing every
deployment to configure every provider.

### Selected Gateway Credential Matrix

| Gateway selector | Token | Required credential behavior |
| --- | --- | --- |
| `mugen.modules.core.gateway.completion` | `deterministic` | No external credential. |
| `mugen.modules.core.gateway.completion` | `openai` | `openai.api.key` must be non-empty and not a placeholder. |
| `mugen.modules.core.gateway.completion` | `azure_foundry` | `azure.foundry.api.key` must be non-empty and not a placeholder. Configure `azure.foundry.api.base_url` for the endpoint. |
| `mugen.modules.core.gateway.completion` | `cerebras` | `cerebras.api.key` must be non-empty and not a placeholder. |
| `mugen.modules.core.gateway.completion` | `groq` | `groq.api.key` must be non-empty and not a placeholder. |
| `mugen.modules.core.gateway.completion` | `sambanova` | `sambanova.api.key` must be non-empty and not a placeholder. |
| `mugen.modules.core.gateway.completion` | `bedrock` | Prefer the ECS task role. If explicit keys are set, `aws.bedrock.api.access_key_id` and `aws.bedrock.api.secret_access_key` must be configured together and not placeholders. |
| `mugen.modules.core.gateway.completion` | `vertex` | Prefer workload identity / ADC where available. If `gcp.vertex.api.access_token` is set, it must not be a placeholder. |
| `mugen.modules.core.gateway.email` | `smtp` | `smtp.username` and `smtp.password` are optional, but must be configured together if either is set. |
| `mugen.modules.core.gateway.email` | `ses` | Prefer the ECS task role. If explicit keys are set, `aws.ses.api.access_key_id` and `aws.ses.api.secret_access_key` must be configured together. `aws.ses.api.session_token` requires both. |
| `mugen.modules.core.gateway.sms` | `twilio` | `twilio.api.account_sid` is required. Configure exactly one auth mode: `twilio.api.auth_token`, or `twilio.api.api_key_sid` plus `twilio.api.api_key_secret`. |
| `mugen.modules.core.gateway.knowledge` | `pinecone` | `pinecone.api.key` must be non-empty and not a placeholder. |
| `mugen.modules.core.gateway.knowledge` | `qdrant` | `qdrant.api.key` is optional, but must not be a placeholder if set. |
| `mugen.modules.core.gateway.knowledge` | `weaviate` | `weaviate.api.key` is optional, but must not be a placeholder if set. |
| `mugen.modules.core.gateway.knowledge` | `milvus` | `milvus.api.token` is optional, but must not be a placeholder if set. |
| `mugen.modules.core.gateway.knowledge` | `chromadb`, `pgvector` | No provider API credential is required by deployment validation. |

Provider implementations may still require non-secret operational values such as
model names, base URLs, hosts, regions, collection names, or endpoint URLs.

## Real-World Overlay Examples

Use `MUGEN_CONFIG_OVERLAY_FILE` for readable local config and
`MUGEN_CONFIG_OVERLAY_JSON` for ECS. These examples show the JSON object before
it is stored in an env var or Secrets Manager value.

### OpenAI Completion

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "completion": "openai"
        }
      }
    }
  },
  "openai": {
    "api": {
      "key": "replace-with-openai-api-key",
      "base_url": "",
      "timeout_seconds": 30.0,
      "completion": {
        "model": "gpt-4.1-mini",
        "surface": "chat_completions",
        "temp": 0.0,
        "top_p": 1.0,
        "max_completion_tokens": 1024
      },
      "classification": {
        "model": "gpt-4.1-mini",
        "surface": "chat_completions",
        "temp": 0.0,
        "top_p": 1.0,
        "max_completion_tokens": 512
      }
    }
  }
}
```

### AWS Bedrock With ECS Task Role

Leave explicit AWS keys blank and grant the ECS task role permission to invoke
the selected model.

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "completion": "bedrock"
        }
      }
    }
  },
  "aws": {
    "bedrock": {
      "api": {
        "region": "us-east-1",
        "access_key_id": "",
        "secret_access_key": "",
        "completion": {
          "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
          "max_completion_tokens": 1024,
          "temp": 0.0,
          "top_p": 0.9
        },
        "classification": {
          "model": "anthropic.claude-3-5-haiku-20241022-v1:0",
          "max_completion_tokens": 512,
          "temp": 0.0,
          "top_p": 0.9
        }
      }
    }
  }
}
```

### SMTP Email

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "email": "smtp"
        }
      }
    }
  },
  "smtp": {
    "host": "smtp.sendgrid.net",
    "port": 587,
    "username": "apikey",
    "password": "replace-with-smtp-password",
    "default_from": "noreply@example.com",
    "timeout_seconds": 30.0,
    "use_ssl": false,
    "starttls": true,
    "starttls_required": true
  }
}
```

### AWS SES With ECS Task Role

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "email": "ses"
        }
      }
    }
  },
  "aws": {
    "ses": {
      "api": {
        "region": "us-east-1",
        "access_key_id": "",
        "secret_access_key": "",
        "session_token": "",
        "endpoint_url": ""
      },
      "default_from": "noreply@example.com",
      "configuration_set_name": ""
    }
  }
}
```

### Twilio SMS

Auth-token mode:

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "sms": "twilio"
        }
      }
    }
  },
  "twilio": {
    "api": {
      "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "auth_token": "replace-with-twilio-auth-token",
      "api_key_sid": "",
      "api_key_secret": "",
      "base_url": "https://api.twilio.com",
      "timeout_seconds": 10.0
    },
    "messaging": {
      "default_from": "+15551234567",
      "messaging_service_sid": ""
    }
  }
}
```

API-key mode:

```json
{
  "twilio": {
    "api": {
      "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "auth_token": "",
      "api_key_sid": "SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "api_key_secret": "replace-with-twilio-api-key-secret"
    }
  }
}
```

### Pinecone Knowledge Gateway

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "knowledge": "pinecone"
        }
      }
    }
  },
  "pinecone": {
    "api": {
      "key": "replace-with-pinecone-api-key",
      "host": "https://your-index-host.svc.pinecone.io",
      "timeout_seconds": 10.0,
      "max_retries": 2,
      "retry_backoff_seconds": 0.5
    },
    "search": {
      "namespace": "production",
      "metric": "cosine",
      "default_top_k": 10,
      "max_top_k": 50,
      "snippet_max_chars": 240
    }
  }
}
```

### Downstream Extension And Migration Track

```json
{
  "mugen": {
    "modules": {
      "extensions": [
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
    }
  },
  "rdbms": {
    "migration_tracks": {
      "plugins": [
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
    }
  },
  "acme_billing": {
    "api": {
      "base_url": "https://billing.example.com",
      "timeout_seconds": 10.0
    }
  }
}
```

Prefer `MUGEN_EXTENSIONS_JSON` and `MUGEN_MIGRATION_TRACKS_JSON` when you need
token/name merge behavior. Generic overlays replace lists.

## Troubleshooting

### Compose Warns That A Long Hash Variable Is Not Set

If Compose prints a warning such as:

```text
The "ac1b19f..." variable is not set. Defaulting to a blank string.
```

it is probably interpolating `$` characters inside a Werkzeug password hash:

```env
ACP_ADMIN_PASSWORD_HASH=scrypt:32768:8:1$salt$hash
```

For local Compose, leave `ACP_ADMIN_PASSWORD_HASH` blank and set
`ACP_ADMIN_PASSWORD`; the overlay generates a local-only hash. If a hash must be
stored in an env file, quote it or escape dollar signs:

```env
ACP_ADMIN_PASSWORD_HASH='scrypt:32768:8:1$salt$hash'
ACP_ADMIN_PASSWORD_HASH=scrypt:32768:8:1$$salt$$hash
```

Compose also auto-loads a root `.env` for interpolation. A stale local `.env`
can trigger warnings even when `--env-file conf/.env.example` is passed.

### Docker Permission Denied

If Docker reports permission denied for `/var/run/docker.sock`, verify group
membership:

```bash
id
getent group docker
ls -l /var/run/docker.sock
```

If the account is in the `docker` group but the current shell is not, start a
new login shell, run `newgrp docker`, or use `sg docker -c 'docker ...'`.

### Overlay File Missing In Container

If `MUGEN_CONFIG_OVERLAY_FILE` points to a file, that file must exist inside the
container. `conf/mugen.overlay.example.json` is copied into the image by the
Dockerfile. Local private overlay files are ignored unless you explicitly mount
or copy them, which is not recommended for ECS secrets.

### ALB Health Checks

Use `/health` for ALB liveness. It only confirms the web process is alive and is
safe for load balancer restarts. Use `/api/core/health/ready` for deeper
readiness diagnostics after the task starts.

## Pre-Commit Deployment Checklist

Run:

```bash
docker build -t mugen-api .
docker compose --env-file conf/.env.example config --quiet
docker compose --env-file conf/.env.example up --build
curl http://localhost:8000/health
docker compose --env-file conf/.env.example run --rm migrate
docker compose --env-file conf/.env.example down
```

Then run the repository pre-push quality gate before committing:

```bash
bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh --python /home/sando/.cache/pypoetry/virtualenvs/mugen-9ZxLq8_f-py3.12/bin/python
```
