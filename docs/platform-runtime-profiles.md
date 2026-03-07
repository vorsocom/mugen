# Platform Runtime Profiles

This document defines the shared runtime-profile model for messaging platforms in
muGen core.

## Scope

The multi-profile runtime model applies to:

- Matrix
- LINE
- Signal
- Telegram
- WeChat
- WhatsApp

The `web` platform does not use transport runtime profiles.

## Configuration Model

Each supported platform now accepts one or more `profiles[]` entries under its
platform config section.

- Shared operational settings stay at the platform root.
- Transport credentials and transport-owned endpoint selectors move into
  `[[<platform>.profiles]]`.
- Every runtime profile requires a unique `key`.
- Legacy single-profile config is still accepted and normalized to one implicit
  runtime profile with key `default`.

Examples:

- Matrix: `[[matrix.profiles]]`
- LINE: `[[line.profiles]]`
- Signal: `[[signal.profiles]]`
- Telegram: `[[telegram.profiles]]`
- WeChat: `[[wechat.profiles]]`
- WhatsApp: `[[whatsapp.profiles]]`

The normalization and lookup behavior is implemented in
[platform_runtime_profile.py](../mugen/core/utility/platform_runtime_profile.py).

## Tenant Binding Model

Tenant-owned channel identity and runtime transport identity are separate.

- `ChannelProfile.profile_key` remains the tenant-facing business identifier.
- `ChannelProfile.runtime_profile_key` selects the configured runtime transport
  profile used for that tenant/channel endpoint.
- `runtime_profile_key` is required for non-web messaging channel profiles.
- `runtime_profile_key` must match one active configured runtime profile for the
  same platform.

This validation is enforced in
[channel_profile.py](../mugen/core/plugin/channel_orchestration/service/channel_profile.py).

## Ingress Routing

Ingress route resolution now carries `runtime_profile_key` in the downstream
route envelope in addition to tenant, binding, and route metadata.

Platform identifier mapping:

| Platform | Identifier type | Identifier value source | Global fallback |
| --- | --- | --- | --- |
| Matrix | `recipient_user_id` | active Matrix runtime profile user id | Yes, for `missing_identifier` and `missing_binding` |
| LINE | `path_token` | webhook path token | No |
| Telegram | `path_token` | webhook path token | No |
| WeChat | `path_token` | webhook path token | No |
| Signal | `account_number` | configured Signal account number | No |
| WhatsApp | `phone_number_id` | webhook payload metadata | No |

Conversation identifiers such as `room_id`, chat ids, or sender phone numbers
still matter, but only as conversation context and reply targets. They are not
the canonical tenant-owned runtime-profile selector.

## Outbound Dispatch

Inbound route metadata includes the selected `runtime_profile_key`, and outbound
dispatch uses that same runtime profile when responding to the conversation.

That means:

- the same tenant can own multiple runtime profiles on one platform;
- the reply uses the same platform account/bot/profile that received the event;
- the external recipient/conversation target still comes from the conversation
  context (`room_id`, reply token, recipient phone number, and so on).

## Platform Runtime Managers

Core DI still exposes one client provider per platform, but the provider now
returns a multi-profile manager for the supported messaging platforms.

Behavior by platform:

- Matrix and Signal run one long-lived task set per runtime profile.
- LINE, Telegram, WeChat, and WhatsApp multiplex outbound calls by runtime
  profile.
- Matrix runtime state and Signal receive-loop state are isolated per runtime
  profile.

## Live Reload

muGen exposes an admin ACP action to reload runtime profiles without a full
process restart:

- entity set: `SystemFlags`
- action: `reloadPlatformProfiles`

Runtime reload behavior:

- rereads the active config file;
- validates the new config;
- reloads only changed active profiled platforms;
- keeps unchanged platforms in place;
- applies reload atomically per platform;
- rolls back already-reloaded platforms if a later platform fails.

Current limitation:

- platform activation changes still require a restart;
- the reload action can reconcile profile changes for active platforms, but it
  cannot turn a platform on or off in place.

The reload logic is implemented in
[platform_runtime_reload.py](../mugen/core/service/platform_runtime_reload.py)
and exposed through ACP in
[system_flag.py](../mugen/core/plugin/acp/service/system_flag.py).
