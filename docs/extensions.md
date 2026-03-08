# Developing muGen Extensions

muGen extensions customize behavior at explicit lifecycle boundaries. The core
runtime now supports five message-lifecycle extension categories:

- `fw`: framework/bootstrap extensions
- `ipc`: typed IPC handlers
- `mh`: message handlers
- `rpp`: response preprocessors
- `ct`: conversational triggers

CTX and RAG are no longer extension categories. Context preparation, retrieval,
bounded state, provenance, cache hints, and post-turn writeback now live behind
the core context engine service boundary. If you need to contribute runtime
context, do it through the context engine plugin contributor interfaces instead
of legacy CTX/RAG hooks.

## Platform Targeting

Every extension declares `platforms`. Return an empty list for platform-agnostic
behavior.

```python
@property
def platforms(self) -> list[str]:
    return ["whatsapp", "web"]
```

## Dependency Injection

Use explicit constructor args for testability. For optional fallback wiring, use
module-level provider callables that resolve from `di.container` at runtime.
Avoid inline `... else di.container.<dep>` expressions and never resolve DI
defaults at import time.

Common services available from `di.container`:

- `config`
- `ingress_service`
- `logging_gateway`
- `ipc_service`
- `messaging_service`
- `platform_service`
- `user_service`
- `context_engine_service`

Extension-provided shared services should be registered through the injector’s
extension-service API, not through module globals.

## Loading Extensions

Extensions are loaded from `mugen.modules.extensions` entries in `mugen.toml`.
Use strict tokens for core extensions and module paths only for your own custom
extension classes where the loader explicitly expects them.

```toml
[[mugen.modules.extensions]]
type = "fw"
path = "extension.app1.fw_ext"

[[mugen.modules.extensions]]
type = "mh"
path = "extension.app1.media_ext"

[[mugen.modules.extensions]]
type = "rpp"
path = "extension.app1.response_ext"
```

`type = "ctx"` and `type = "rag"` are rejected by bootstrap validation.

## Message Handler Extensions

MH extensions handle inbound message types such as `image`, `audio`, `file`, or
custom text paths. Their runtime method is scope-aware.

```python
from typing import Any

from mugen.core.contract.context import ContextScope
from mugen.core.contract.extension.mh import IMHExtension


class MyMHExtension(IMHExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def message_types(self) -> list[str]:
        return ["image"]

    async def handle_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        *,
        scope: ContextScope,
    ) -> list[dict] | None:
        return [
            {
                "type": "image_summary",
                "content": {"caption": "Processed image", "tenant_id": scope.tenant_id},
            }
        ]
```

`mugen.messaging.mh_mode` controls whether the runtime may fall back to the
built-in text handler when no MH extension handles a text turn.

## IPC Extensions

IPC extensions process typed command requests and return typed handler results.

```python
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult


class MyIPCExtension(IIPCExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def ipc_commands(self) -> list[str]:
        return ["ping"]

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        return IPCHandlerResult(
            handler=type(self).__name__,
            response={"status": "ok", "command": request.command},
        )
```

## Command Processor Extensions

CP extensions handle explicit commands before normal text completion runs.

```python
from mugen.core.contract.context import ContextScope
from mugen.core.contract.extension.cp import ICPExtension


class MyCommandExtension(ICPExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return ["/status"]

    async def process_message(
        self,
        message: str,
        room_id: str,
        user_id: str,
        *,
        scope: ContextScope,
    ) -> list[dict] | None:
        return [{"type": "text", "content": f"tenant={scope.tenant_id}"}]
```

## Response Pre-processor Extensions

RPP extensions receive the final assistant text before the user sees it.

```python
from mugen.core.contract.context import ContextScope
from mugen.core.contract.extension.rpp import IRPPExtension


class MyRPPExtension(IRPPExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    async def preprocess_response(
        self,
        room_id: str,
        user_id: str,
        assistant_response: str,
        *,
        scope: ContextScope,
    ) -> str:
        return f"[{scope.tenant_id}] {assistant_response}"
```

## Conversational Trigger Extensions

CT extensions observe the final assistant text and may trigger downstream
operations.

```python
from mugen.core.contract.context import ContextScope
from mugen.core.contract.extension.ct import ICTExtension


class MyCTExtension(ICTExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def triggers(self) -> list[str]:
        return ["handoff"]

    async def process_message(
        self,
        message: str,
        role: str,
        room_id: str,
        user_id: str,
        *,
        scope: ContextScope,
    ) -> None:
        _ = (message, role, room_id, user_id, scope)
```

## Framework Extensions

FW extensions run during startup and are the correct place to register plugin
services, ACP contributors, migration tracks, or runtime collaborator bindings.

The core context engine plugin uses an FW extension token:

- `core.fw.context_engine`

That FW extension registers the shared context component registry, default
contributors, ACP resource contributions, and plugin-owned migration track
hooks.

## Context Contributors

To extend context behavior itself, implement context-engine collaborators rather
than message-lifecycle extensions. The main ports live in
`mugen.core.contract.context`:

- `IContextContributor`
- `IContextGuard`
- `IContextRanker`
- `IMemoryWriter`
- `IContextCache`
- `IContextTraceSink`

Context contributors emit typed `ContextCandidate` artifacts with provenance and
estimated token cost. They are tenant-scoped by `ContextScope` and are composed
through the context engine plugin’s runtime registry.

See `docs/context-engine-design.md` for the runtime contract and control-plane
shape.
