# Service Profiles

The opt-in `core.fw.service_profile` extension provides a stable, channel-neutral
service identity inside a tenant. A Service Profile connects routed ingress,
an exact Billing Subscription allocation, usage provenance, and Knowledge Pack
scope without defining application-facing roles, industries, or channel-specific
behavior.

## Enable the extension

Configure Service Profile after ACP, Billing, Channel Orchestration, and
Knowledge Pack:

```toml
[[mugen.modules.extensions]]
type = "fw"
token = "core.fw.service_profile"
enabled = true
critical = true
name = "com.vorsocomputing.mugen.service_profile"
namespace = "com.vorsocomputing.mugen.service_profile"
models = "mugen.core.plugin.service_profile.model"
migration_track = "core"
contrib = "mugen.core.plugin.service_profile.contrib"
```

Apply the Core migration and reseed ACP after enabling the extension. ACP
reseed creates the resource metadata and grants `read`, `create`, `update`, and
`manage` to the ACP administrator role. The resources intentionally expose no
normal DELETE or restore operation.

The extension is critical when enabled. Startup fails with the unavailable
dependency named in the error if ACP, SQLAlchemy relational storage, Ingress
Binding resources, Billing account/subscription/catalog resources, or Knowledge
Scope resources are missing.

## Provisioning lifecycle

Provision a routable service in this order:

1. Create the Channel Profile or client configuration and its active Ingress
   Binding.
2. Create a draft `ServiceProfiles` resource.
3. Create one or more active `ServiceProfileIngressBindings` assignments.
4. Create the Billing Account-owned Billing Subscription.
5. Create and activate a `ServiceProfileSubscriptions` assignment. Core derives
   its normalized `ProductCode`; clients must not supply it.
6. Configure consumers and Knowledge Scopes with the stable `ServiceProfileId`.
7. Activate the Service Profile.

The Billing Account owns the Subscription. The Service Profile receives access
to the Product through one exact allocation. The Ingress Binding remains the
authority for endpoint identity and service-route resolution. Consumers remain
responsible for service-specific behavior.

A profile can own several active Ingress Binding assignments, but one live
Ingress Binding resolves to at most one active profile. A Billing Subscription
can be actively allocated to only one profile. A profile can have several
Products, but only one active allocation for a given normalized Product code.
Reassignment requires disabling the existing allocation and creating a new one.

Profiles transition `draft -> active -> disabled`; disabled is terminal.
Subscription assignments use the same lifecycle. Profile activation requires
at least one assignment whose live Ingress Binding is still active. Disabling a
profile does not rewrite assignment rows, but ingress and entitlement resolution
exclude it immediately.

## Runtime contracts

Resolve routed service identity with
`IServiceProfileResolver.resolve(tenant_id, ingress_binding_id)`. A successful
result contains the tenant, Service Profile ID, normalized key, and display
name. Missing, inactive, deleted, cross-tenant, or ambiguous graphs return a
fail-closed reason code rather than an ORM object.

Resolve commercial access with
`IServiceProfileEntitlementService.resolve(tenant_id, service_profile_id,
product_code)`. A successful result preserves the exact assignment, Billing
Account, Billing Subscription, Price, Product, normalized Product code,
Subscription status, and current-period boundaries. Runtime resolution
revalidates the live Subscription period/status and global catalog. It never
substitutes another Subscription with the same Product. A changed live Product
code returns the distinct `catalog_drift` reason and requires an explicit new
allocation.

Period starts are inclusive and ends are exclusive. `active` and `trialing`
Subscriptions are eligible only when started, inside their current period,
not effectively cancelled, not cancelled or ended, and not deleted. A scheduled
cancellation remains eligible until `cancel_at`.

## Knowledge Pack scope

`KnowledgeScopes.ServiceProfileId` is optional and independent of
`ServiceRouteKey` and `ClientProfileKey`:

- `ServiceProfileId` is the stable routable service identity.
- `ServiceRouteKey` selects routed behavior.
- `ClientProfileKey` identifies channel-client configuration or credentials.

When a search requests a Service Profile, an exact scope or a `NULL` wildcard
scope is eligible, with the exact scope ranked first. Without a requested
Service Profile, only `NULL` Service Profile scopes are eligible. Projection
construction may include a draft profile to support the provisioning order,
but safe retrieval revalidates tenant ownership and requires the requested and
stored profiles to be active and not deleted.

Knowledge Pack projection schema version 2 includes `service_profile_id` in
document metadata and checksums. Reindex existing published versions after
preparing an external provider schema. Old projections are not profile-aware.

## External knowledge gateway schema

Every configured provider must retain `service_profile_id` as optional governed
metadata and return it on search hits:

- pgvector: nullable UUID column named `service_profile_id`.
- Chroma, Pinecone, Qdrant: optional filterable metadata/payload keyword.
- Milvus: optional nullable string/UUID-compatible governed field (or enabled
  dynamic field) returned by searches.
- Weaviate: optional text/UUID-compatible property returned by governed queries.

Provider schema changes must be deployed before reindexing. Core performs final
exact-or-wildcard filtering and relational revalidation for every provider and
never treats provider-stored snippets or bodies as authoritative content.
