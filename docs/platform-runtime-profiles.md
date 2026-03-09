# ACP Messaging Client Profiles

This document defines the current messaging client profile model in muGen core.

## Scope

The ACP-owned client profile model applies to:

- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

The `web` platform is out of scope.

## Source Of Truth

Messaging transport accounts now live in the ACP `MessagingClientProfiles`
entity set.

- Config keeps only process-level platform settings such as timeouts, allow
  lists, media limits, and bind/runtime switches.
- Tenant-owned transport credentials, webhook selectors, and account identifiers
  live in ACP rows plus ACP `KeyRef` secrets.
- A deployment may start with zero active client profiles for any enabled
  messaging platform.

Each `MessagingClientProfiles` row owns:

- `platform_key`
- `profile_key`
- `display_name`
- `is_active`
- `settings`
- `secret_refs`
- lookup identifiers such as `path_token`, `recipient_user_id`,
  `account_number`, `phone_number_id`, and `provider`

Client-profile-specific sender gates also live in `settings` when supported by
the platform:

- Matrix: `user_access.mode` plus `user_access.users`
- WhatsApp: `user_access.mode`, `user_access.users`, and optional
  `user_access.denied_message`

Supported access modes are:

- `allow-all`
- `allow-all-except`
- `allow-only`

Tenant-editable non-secret platform defaults now live in ACP
`RuntimeConfigProfiles` rows rather than operator-owned TOML.

- `Category = "messaging.platform_defaults"` with `ProfileKey = <platform>`
  stores tenant/global non-secret runtime overlays for the supported messaging
  platforms.
- `Category = "ops_connector.defaults"` with `ProfileKey = "default"` stores
  tenant/global retry and redaction defaults for `ops_connector`.
- Resolution is tenant row first, then global row, then process config.

Tenant-facing secrets should use ACP `KeyRef` rows with `provider="managed"`.
The operator-owned `local` provider remains for bootstrap and emergency use only.

## Channel Binding Model

`ChannelProfile` remains the tenant-facing business profile, but it now points
to a transport account by `client_profile_id`.

- `ChannelProfile.profile_key` remains the tenant-facing business identifier.
- `ChannelProfile.client_profile_id` selects the ACP-owned transport account.
- Validation is same-tenant and same-platform fail-closed.

The global tenant may own explicit client profiles, but there is no implicit
platform fallback to the global tenant.

## Ingress Routing

Ingress route resolution now carries `client_profile_id` and optional
`client_profile_key` in the downstream route envelope.

Platform identifier mapping:

| Platform | Identifier type | Identifier value source |
| --- | --- | --- |
| Matrix | `recipient_user_id` | active Matrix client profile user id |
| LINE | `path_token` | ACP client profile webhook path token |
| Telegram | `path_token` | ACP client profile webhook path token |
| WeChat | `path_token` | ACP client profile webhook path token |
| Signal | `account_number` | ACP client profile account number |
| WhatsApp | `phone_number_id` | ACP client profile phone number id |

Unresolved messaging ingress now fails closed across all six platforms.

## Shared Ingress Persistence

The shared ingress tables persist `client_profile_id` on every canonical row.

Practical consequences:

- dedupe is scoped by `platform + client_profile_id + dedupe_key`;
- dead-letter and replay stay isolated per client profile;
- worker dispatch preserves the client profile that received the event;
- Matrix sync checkpoints are stored per `client_profile_id`.

See [Messaging Ingress Contract](./messaging-ingress-contract.md).

## Outbound Dispatch

Inbound route metadata includes the selected `client_profile_id`, and outbound
dispatch uses that same client profile when responding.

That means:

- one tenant may own multiple client profiles on one platform;
- replies go out through the same transport account that received the event;
- `client_profile_key` is optional debug metadata only.

## Runtime Managers And Reload

Core DI still exposes one client provider per platform, but each messaging
provider now resolves active clients from ACP.

Behavior by platform:

- Matrix and Signal run one long-lived task set per active client profile.
- LINE, Telegram, WeChat, and WhatsApp multiplex outbound calls by active
  client profile.

Live reload still uses the `SystemFlags.reloadPlatformProfiles` ACP action, but
the reload target is now the ACP-owned client profile catalog plus the current
process-level config.

## Legacy Import

Use `scripts/import_legacy_runtime_config.py` to import:

- legacy `[[<platform>.profiles]]` blocks as global `MessagingClientProfiles`;
- operator-local ACP key maps as managed `KeyRefs`;
- global `ops_connector` defaults as `RuntimeConfigProfiles`.

The import is idempotent and does not edit local config files. After a
successful run, remove legacy `profiles` blocks and local key maps manually
once the imported ACP rows are verified.

For Matrix, device verification data is available through ACP runtime read
endpoints, including tenant-scoped reads for tenant-owned active runtime client
profiles.
