# Knowledge Pack Downstream Developer Guide

- Status: current
- Owner: downstream plugin team
- Last Updated: 2026-06-04

## Context

`knowledge_pack` is the core source of truth for governed knowledge content.
It stores pack/version/revision/scope state in the relational database and
exposes that state through ACP resources and actions.

Downstream teams commonly add search projections, ranking, redaction, authoring
UIs, or channel-specific answer contracts. Those downstream layers must treat
core `knowledge_pack` rows as authoritative for publication state and scope.
Vector or keyword gateways are retrieval accelerators, not the governance
source of truth.

## Decision

- Use ACP `knowledge_pack` resources for content lifecycle and scope ownership.
- Use `KnowledgeScopeService.list_published_revisions(...)` for production
  published/scope candidate resolution.
- Route-aware context-engine traffic should rely on
  `KnowledgePackContributor`, which passes ingress route/profile metadata into
  the scope service before emitting evidence artifacts.
- Keep downstream search gateways and projections read-only with respect to
  `knowledge_pack` governance state.
- Preserve the emitted context artifact shape so source policy, guards, rankers,
  traces, and renderers continue to reason over `knowledge_pack_revision`
  sources.

## Core vs Downstream Boundary

Core responsibilities:

- Store tenant-scoped knowledge packs, versions, entries, revisions, approvals,
  and scopes in the RDBMS.
- Expose ACP entity sets:
  - `KnowledgePacks`
  - `KnowledgePackVersions`
  - `KnowledgeEntries`
  - `KnowledgeEntryRevisions`
  - `KnowledgeApprovals`
  - `KnowledgeScopes`
- Enforce version workflow states and publication transitions.
- Enforce published-only lookup in `KnowledgeScopeService`.
- Enforce knowledge scope dimensions:
  - `tenant_id`
  - `channel`
  - `locale`
  - `category`
  - `service_route_key`
  - `client_profile_key`
- Emit context-engine evidence artifacts through `KnowledgePackContributor`.

Downstream responsibilities:

- Build content authoring/import workflows around the ACP resources.
- Define product-specific search projections, analyzers, ranking, snippets, and
  answer contracts.
- Add redaction or compliance checks before indexing or displaying excerpts.
- Reconcile downstream search indexes against published RDBMS source state.
- Decide how channel UX exposes citations, snippets, scores, and fallbacks.

## Implementation Sketch

### ACP Lifecycle

The ACP surface uses PascalCase payload fields. Create and publish knowledge in
this order:

1. Create a `KnowledgePacks` row.
2. Create a `KnowledgePackVersions` row for that pack.
3. Create `KnowledgeEntries` for version-owned content items.
4. Create `KnowledgeEntryRevisions` with `Body` or `BodyJson`.
5. Create `KnowledgeScopes` that bind candidate revisions to retrieval
   dimensions.
6. Move the version through `submit_for_review`, `approve`, and `publish` on
   `KnowledgePackVersions`.

Minimal resource payloads:

```json
{
  "TenantId": "uuid",
  "Key": "refund-policy",
  "Name": "Refund Policy"
}
```

```json
{
  "TenantId": "uuid",
  "KnowledgePackId": "uuid",
  "VersionNumber": 1,
  "Note": "Initial refund guidance"
}
```

```json
{
  "TenantId": "uuid",
  "KnowledgePackId": "uuid",
  "KnowledgePackVersionId": "uuid",
  "EntryKey": "partial-refunds",
  "Title": "Partial refund guidance",
  "Summary": "Rules for partially used packages"
}
```

```json
{
  "TenantId": "uuid",
  "KnowledgeEntryId": "uuid",
  "KnowledgePackVersionId": "uuid",
  "RevisionNumber": 1,
  "Body": "Partially used packages are handled by the published refund matrix.",
  "Channel": "refund-desk",
  "Locale": "en-US",
  "Category": "refunds"
}
```

```json
{
  "TenantId": "uuid",
  "KnowledgePackVersionId": "uuid",
  "KnowledgeEntryRevisionId": "uuid",
  "Channel": "refund-desk",
  "Locale": "en-US",
  "Category": "refunds",
  "ServiceRouteKey": "valet.customer_inbox",
  "ClientProfileKey": "vip-sms",
  "IsActive": true
}
```

Workflow action payloads include the current `RowVersion`:

```json
{
  "RowVersion": 1,
  "Note": "Approved by support policy owner"
}
```

### Authorization

`knowledge_pack` ACP resources are tenant-scoped. Global ACP administrators
receive seeded access through the ACP manifest, but tenant members must be
granted tenant-scoped ACP roles and permission entries for the tenant they are
allowed to manage.

Downstream UIs should not gate knowledge-pack configuration screens on the
global ACP administrator role. Use the stable feature permission below for
route visibility:

```text
com.vorsocomputing.mugen.knowledge_pack:configurator
```

That permission is returned in the ACP auth `roles` array when the user has it
for at least one tenant, or when the user is a global ACP administrator. It is a
coarse UI visibility signal. Server-side access remains enforced by the tenant
ACP routes and the concrete resource/action grants described below.

For tenant authoring access, grant tenant roles permission entries against the
knowledge-pack resource permission objects using standard ACP permission types:

| Capability | Permission object | Permission type |
| --- | --- | --- |
| Read packs, versions, entries, revisions, approvals, scopes | `com.vorsocomputing.mugen.knowledge_pack:<resource_object>` | `com.vorsocomputing.mugen.acp:read` |
| Create packs, versions, entries, revisions, scopes | `com.vorsocomputing.mugen.knowledge_pack:<resource_object>` | `com.vorsocomputing.mugen.acp:create` |
| Update packs, versions, entries, revisions, scopes | `com.vorsocomputing.mugen.knowledge_pack:<resource_object>` | `com.vorsocomputing.mugen.acp:update` |

Resource object names are the snake_case form of the ACP entity:

- `knowledge_pack`
- `knowledge_pack_version`
- `knowledge_entry`
- `knowledge_entry_revision`
- `knowledge_approval`
- `knowledge_scope`

The default ACP admin namespace is `com.vorsocomputing.mugen.acp`; if a
deployment overrides the ACP framework namespace, use that configured namespace
for standard `read`, `create`, and `update` permission types.

Version lifecycle actions use action-specific permission types on the
`knowledge_pack_version` permission object:

| Action | Permission type |
| --- | --- |
| `submit_for_review` | `com.vorsocomputing.mugen.knowledge_pack:submit_for_review` |
| `approve` | `com.vorsocomputing.mugen.knowledge_pack:approve` |
| `reject` | `com.vorsocomputing.mugen.knowledge_pack:reject` |
| `publish` | `com.vorsocomputing.mugen.knowledge_pack:publish` |
| `archive` | `com.vorsocomputing.mugen.knowledge_pack:archive` |
| `rollback_version` | `com.vorsocomputing.mugen.knowledge_pack:rollback_version` |

This allows downstream products to split tenant roles by responsibility:

- readers get `read` grants plus the configurator visibility permission;
- authors get `create` and `update` grants plus `submit_for_review`;
- reviewers get `approve` and `reject`;
- publishers get `publish`, `archive`, and `rollback_version`.

If a deployment overrides the knowledge-pack plugin namespace, use the
configured namespace for resource permission objects and lifecycle action
permission types. The stable configurator permission remains unchanged.

### Scope Semantics

`KnowledgeScopeService.list_published_revisions(...)` returns only revisions
whose owning version and revision are both `published`.

Tenant filtering is mandatory. `channel`, `locale`, and `category` preserve the
legacy behavior:

- `channel` is matched exactly when supplied by the caller.
- `locale` is matched exactly when supplied by the caller.
- `category` is matched exactly when supplied by the caller.
- if `locale` or `category` is omitted, the current service does not constrain
  that dimension.

`service_route_key` and `client_profile_key` use route-aware fallback rules:

| Request value | Matching scope values |
| --- | --- |
| value present | exact value or `NULL` |
| value absent | `NULL` only |

This means routed/profiled traffic can see matching specific scopes plus generic
fallback scopes, while unrelated route/profile-specific scopes are excluded.
If the same revision is matched by several scopes, the service returns it once
and orders more-specific route/profile matches before generic matches.

### Context Engine Wiring

`KnowledgePackContributor` reads route/profile data from
`request.ingress_metadata["ingress_route"]` first and falls back to top-level
`request.ingress_metadata` fields. It passes:

- `service_route_key`
- `client_profile_key`
- `locale`
- `category`
- `channel=request.scope.channel_id or request.scope.platform`

to `KnowledgeScopeService.list_published_revisions(...)`.

Expected ingress metadata:

```json
{
  "locale": "en-US",
  "category": "refunds",
  "ingress_route": {
    "service_route_key": "valet.customer_inbox",
    "client_profile_key": "vip-sms"
  }
}
```

The contributor emits `ContextCandidate` values with:

- `lane="evidence"`
- `kind="knowledge_span"`
- `render_class="evidence_items"`
- provenance `source_kind="knowledge_pack_revision"`
- source key derived from revision metadata
- locale and category on the source reference

`ContextSourceBindings` can further allow source refs by `source_kind`,
`source_key`, platform, channel key, locale, category, and
`service_route_key`. They do not currently carry `client_profile_key`, so use
`KnowledgeScope.ClientProfileKey` for profile-specific retrieval isolation.

### Search Projection Pattern

If downstream code needs BM25, vector search, or hybrid ranking, keep a
downstream projection table or provider index tied back to
`knowledge_entry_revision_id`.

A revision can have multiple `KnowledgeScopes`. Do not overwrite scope metadata
into a single unique revision row unless your projection stores scopes in a
separate table. Valid designs include:

- one content table keyed by `knowledge_entry_revision_id` plus one scope table
  keyed by source scope identity;
- one denormalized search document per revision/scope row with a stable
  projection document key;
- one provider object per revision plus an independent candidate-ID gate that
  calls `KnowledgeScopeService` before provider ranking.

Projection content/scope data should include, at minimum:

- `tenant_id`
- `knowledge_pack_id`
- `knowledge_pack_version_id`
- `knowledge_entry_revision_id`
- `channel`
- `locale`
- `category`
- `service_route_key`
- `client_profile_key`
- searchable text fields
- projection/index metadata

The recommended retrieval flow is:

1. Use `KnowledgeScopeService.list_published_revisions(...)` to resolve the
   governed candidate revision IDs.
2. Search/rank only inside that candidate set, or enforce the same route/profile
   fallback rules in the downstream projection before ranking.
3. Return citation payloads that include the revision and version identifiers.
4. Never serve draft, review, approved-but-unpublished, archived, or unrelated
   route/profile-specific rows from the projection.

The generic knowledge gateway contract currently accepts tenant/channel/locale/
category filters only. Do not rely on those gateways alone for route/profile
isolation unless your downstream projection contract has explicitly added and
tested those dimensions.

## Validation

Downstream implementations should cover:

- ACP create/update validation for blank and valid scope fields.
- Tenant RBAC tests proving non-admin tenant users can access only the
  knowledge-pack resource/action permissions their tenant role grants.
- Auth-session tests proving `com.vorsocomputing.mugen.knowledge_pack:configurator`
  is returned for tenant users who have the feature visibility grant.
- Version workflow tests for submit, approve, publish, archive, and rollback.
- Published-only retrieval tests.
- Route/profile tests:
  - exact route/profile scopes are included;
  - `NULL` route/profile scopes remain generic fallbacks;
  - unrelated route/profile scopes are excluded;
  - no-route requests do not receive route/profile-specific scopes;
  - duplicated scope matches return each revision once.
- Context-engine integration proving ingress route metadata reaches knowledge
  lookup and selected evidence is matching or generic only.
- Projection drift checks comparing downstream indexed revision IDs against
  published RDBMS candidates.

## Risks / Open Questions

- The generic knowledge gateways do not yet expose first-class route/profile
  filters; downstream projections must handle those dimensions deliberately.
- `ContextSourceBindings` are service-route-aware but not client-profile-aware.
- `locale` and `category` omission currently leaves those dimensions
  unconstrained; downstream strict contracts may choose to require them.
- Product teams still own answer formatting, ranking policy, snippet limits,
  redaction, and citation UX.
