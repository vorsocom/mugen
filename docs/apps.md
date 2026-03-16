# Building Downstream muGen Applications

Status: Active  
Last Updated: 2026-03-16  
Audience: Downstream application teams, plugin maintainers

muGen is meant to be extended, but the extension path matters. The goal for a
downstream application is to add business behavior, policies, and integrations
without collapsing the core architecture or forking `mugen/core` into an
unmaintainable custom platform.

Use this guide for the downstream workflow. Use
[`docs/downstream-architecture-conformance.md`](./downstream-architecture-conformance.md)
for the non-negotiable architecture rules and extension-boundary checklist.

## Start With An Upstream/Downstream Workflow

Treat the official `vorsocom/mugen` repository as upstream and your product
repository as downstream.

```shell
~$ git clone git@github.com:vorsocom/mugen.git hrms-agent
~$ cd hrms-agent
~$ git remote rename origin upstream
~$ git remote set-url --push upstream PUSH_DISABLED
~$ git remote add origin [downstream-repo-url]
~$ git checkout -b develop
```

Track downstream provenance in a separate metadata file at the project root,
for example `downstream.toml`, rather than in runtime config or
`pyproject.toml`.

```shell
~$ cp conf/downstream.toml.sample downstream.toml
```

Use this file for provenance only:

- `upstream.sync_ref` is required and should record the exact upstream commit
  currently merged into the downstream repository.
- `upstream.sync_tag` is optional and should be set only when that synced
  commit corresponds to an upstream tag.
- `upstream.branch` should match the upstream branch you actually integrate
  from. Use `main` only when release-based syncs are your baseline.
- Keep runtime settings, secrets, local paths, and machine-specific values out
  of this file.

This keeps upstream syncs explicit and makes it easier to distinguish framework
changes from product-specific behavior.

## Keep Custom Code Outside `mugen/core`

Downstream code should live in your own import package, not under
`mugen/core`.

Recommended layout:

```text
hrms-agent/
├── downstream.toml
├── mugen/
├── acme_extension/
│   ├── __init__.py
│   ├── contrib.py
│   ├── fw_ext.py
│   ├── service/
│   ├── model/
│   └── migrations/
├── conf/
├── docs/
├── mugen.toml
└── hypercorn.toml
```

Practical rules:

- keep downstream business logic, projections, workers, and ACP-aligned plugin
  code in a top-level package such as `acme_extension` or `my_org_support`;
- leave `mugen/core` unchanged unless you are intentionally contributing a core
  framework change upstream;
- wire downstream extensions and model modules through `mugen.toml`, not by
  importing them directly into core packages.

## Configure muGen For Downstream Extensions

Create local config from the samples:

```shell
~$ cp conf/downstream.toml.sample downstream.toml
~$ cp conf/mugen.toml.sample mugen.toml
~$ cp conf/hypercorn.toml.sample hypercorn.toml
```

Use `mugen.modules.extensions` for runtime extension wiring.

Core runtime extensions use strict tokens. Downstream ACP-aligned framework
plugins declare their identity and contributor metadata on enabled `fw`
entries. The current bootstrap extension registry itself is token-based; do not
assume arbitrary module-path loading for custom runtime extension classes.

```toml
[[mugen.modules.extensions]]
type = "fw"
token = "core.fw.acp"
enabled = true
name = "com.vorsocomputing.mugen.acp"
namespace = "com.vorsocomputing.mugen.acp"
contrib = "mugen.core.plugin.acp.contrib"

[[mugen.modules.extensions]]
type = "fw"
token = "acme.fw.billing"
enabled = true
name = "com.acme.billing"
namespace = "com.acme.billing"
contrib = "acme_extension.contrib"
models = "acme_extension.model"
migration_track = "acme_extension"

[[rdbms.migration_tracks.plugins]]
name = "acme_extension"
enabled = true
alembic_config = "acme_extension/migrations/alembic.ini"
schema = "acme_extension"
version_table = "alembic_version"
version_table_schema = "acme_extension"
model_modules = ["acme_extension.model"]
```

See [`docs/extensions.md`](./extensions.md) for extension types and
[`docs/migration-track-separation.md`](./migration-track-separation.md) for the
migration-track contract.

If you need the runtime to instantiate a brand-new non-core CP/MH/RPP/CT/FW
extension class directly, treat that as a framework-extension-registry change,
not as a pure downstream config task.

## Choose The Right Extension Boundary

Use the narrowest seam that matches the behavior you are adding:

- use ACP-backed framework plugins when you need new resources, actions,
  runtime binding, or admin/API registration;
- use command, message-handler, response-preprocessor, or conversational
  trigger extensions for messaging-path customization when the runtime already
  exposes the required token/registry support;
- use context-engine collaborators when the change is about retrieval, state,
  provenance, ranking, or context compilation;
- use agent-runtime collaborators when the change is about planning,
  evaluation, capability execution, or resumable background work;
- keep product-specific workflow policy, projections, SLA logic, and external
  side effects in downstream packages and workers.

If a change can be expressed without editing `mugen/core`, it should be.

## Install, Migrate, And Run

```shell
~$ poetry install
~$ poetry shell
~$ python scripts/run_migration_tracks.py upgrade head
~$ hypercorn -c hypercorn.toml quartman
```

Startup lifecycle:

1. **Phase A (blocking):** bootstrap extensions and register API routes.
2. **Phase B (background):** start long-running platform clients and workers.

Requests are served only after Phase A completes successfully.

For local development and testing, you can still use the telnet harness:

```shell
~$ python -m mugen.devtools.telnet_harness
~$ telnet localhost 8888
```

## Keep Downstream Repositories Conformant

Recommended guardrails:

1. Sync upstream through a branch and PR instead of merging directly into
   `develop`.
2. Block accidental edits to `mugen/core/` in downstream feature PRs unless the
   change is an intentional upstream contribution.
3. Keep downstream schema in plugin-owned migration tracks, not in
   `migrations/versions`.
4. Treat ACP resources/actions as the control plane for core-owned domains
   instead of writing directly to core tables.
5. Keep the core architecture-boundary tests passing and add downstream tests
   for your own package boundaries.
6. Run the full project quality gates after upstream syncs and before release
   candidates.

For architecture-specific rules, decision points, and a checklist that is safe
to hand to an AI coding agent, see
[`docs/downstream-architecture-conformance.md`](./downstream-architecture-conformance.md).
