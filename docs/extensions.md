# Developing muGen Extensions

muGen extensions are modular components that allow developers to customize and extend the framework’s capabilities by adding platform-agnostic or platform-specific behaviors at different stages of the message lifecycle. There are seven extension types: Framework (FW) extensions for integrating core features, Inter-process Communication (IPC) extensions for managing commands and scheduled tasks, Message Handler (MH) extensions for processing non-text inputs, Context (CTX) extensions for enriching conversation histories, Retrieval Augmented Generation (RAG) extensions for performing knowledge retrieval, Response Pre-processor (RPP) extensions for adjusting LLM responses, and Conversational Trigger (CT) extensions for detecting cues and initiating actions. By using object-oriented programming (OOP) interfaces and dependency injection, these extensions enhance the flexibility, maintainability, and reusability of muGen applications.

## Prerequisites

Before starting, make sure you have:

1. Followed the guide on [building muGen applications](apps.md) and set up a project repository.
2. Familiarity with Python programming, [object-oriented programming (OOP)](https://en.wikipedia.org/wiki/Object-oriented_programming), and [dependency injection](https://en.wikipedia.org/wiki/Dependency_injection).

## The Extension Directory

While extension modules can be loaded from anywhere in the directory structure, we recommended creating an `extension` directory in the project root.

```text
root
└── extension
    └── ...
```

As a best practice, consider grouping extensions that serve the same business use case into "app" directories. This would make it easier to reuse the functionality they provide in other systems. For example:

```text
root
└── extension
    ├── app1
    │   ├── ctx_ext.py
    │   └── rag_ext.py
    └── app2
        └── mh_ext.py
```

You can use your own naming conventions for extension directories and files.

## Interfaces

muGen provides contracts (OOP interfaces) for the different extension types it supports. These interfaces are located in `mugen.core.contract.extension`. For example, if you want to create a Context extension, you would import the interface as follows:

```python
from mugen.core.contract.extension.ctx import ICTXExtension
```

Remember that your extensions must strictly conform to the specified contracts as the framework will never access your extensions directly, but rather through these interfaces.

## Platform Targeting

All extensions must declare their target platform(s) using the `platforms` property, which must return a list of strings. Platform targeting ensures that an extension is only applied when interacting with specified platforms. For example, if you have features that are specific to WhatsApp and Telnet, setting up platform targeting allows your extension to activate only when the corresponding platform is in use.

For platform-agnostic extensions, the `platforms` property should return an empty list.

```python
@property
def platforms(self) -> list[str]:
    """Get the platforms this extension supports."""
    # This extension targets the telnet and WhatsApp platforms.
    return ["telnet", "whatsapp"]

```

## Dependency Injection

Dependency injection allows extensions to access application configuration, core clients, gateways, and services in a flexible manner without hardcoding dependencies. This approach makes the code more modular and easier to maintain, as dependencies are managed by the framework instead of being directly instantiated within the extension. The `mugen.core.di` module is used to enable this feature.

For example, a Context extension that requires access to the TOML configuration and logging could have the following setup.


```python

from mugen.core import di
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.gateway.logging import ILoggingGateway


class MyCTXExtension(ICTXExtension):
    
    def __init__(
        self,
        config=di.container.config,
        logging_gateway=di.container.logging_gateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway

        self._logging_gateway.info("Init complete.")
        self._logging_gateway.info(
            f"Application environment: {self._config.mugen.environment}"
        )

    ...
```

The following is a listing of available clients, gateways, and services.

* Clients:
    * [Matrix](/mugen/core/contract/client/matrix.py) (di.container.matrix_client)
    * [Telnet](/mugen/core/contract/client/telnet.py) (di.container.telnet_client)
    * [WhatsApp](/mugen/core/contract/client/whatsapp.py) (di.container.whatsapp_client)
* Gateways:
    * [Completion](/mugen/core/contract/gateway/completion.py) (di.container.completion_gateway)
    * [Knowledge](/mugen/core/contract/gateway/knowledge.py) (di.container.knowledge_gateway)
    * [Logging](/mugen/core/contract/gateway/logging.py) (di.container.logging_gateway)
    * Storage:
        * [key-val](/mugen/core/contract/gateway/storage/keyval.py) (di.container.keyval_storage_gateway)
* Services:
    * [IPC](/mugen/core/contract/service/ipc.py) (di.container.ipc_service)
    * [Messaging](/mugen/core/contract/service/messaging.py) (di.container.messaging_service)
    * [NLP](/mugen/core/contract/service/nlp.py) (di.container.nlp_service)
    * [Platform](/mugen/core/contract/service/platform.py) (di.container.platform_service)
    * [User](/mugen/core/contract/service/user.py) (di.container.user_service)

## Loading extensions

Extensions are loaded by setting their type and path in `mugen.toml`.

```toml
...
[[mugen.modules.extensions]]
type = "ctx"
path = "mugen.extension.app1.ctx_ext"

[[mugen.modules.extensions]]
type = "rag"
path = "mugen.extension.app1.rag_ext"

[[mugen.modules.extensions]]
type = "mh"
path = "mugen.extension.app2.mh_ext"
...
```

For now, and unfortunately, extensions have to be wired for loading individually, even if they are in the same app directory. Hopefully, as the framework matures, a better loading mechanism will be implemented.

## Extension Types

### Framework (FW) Extensions

Framework extensions add core functionalities to the muGen framework and are initialized during application startup. Implement the `IFWExtension` interface to create a Framework extension.

**Setup Code:**

```python
"""Provides an implementation for IFWExtension."""

__all__ = ["MyFWExtension"]

from mugen.core.contract.extension.fw import IFWExtension


class MyFWExtension(IFWExtension):
    """Custom implementation of IFWExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    async def setup(self) -> None:
        """Perform extension setup during application initialization."""
        print("Setting up MyFWExtension...")
        # Add custom setup logic here
```

### Inter-process Communication (IPC) Extensions

IPC extensions handle background tasks, push notifications, and scheduled operations. Implement the `IIPCExtension` interface to create an IPC extension.

**Setup Code:**

```python
"""Provides an implementation for IIPCExtension."""

__all__ = ["MyIPCExtension"]

from mugen.core.contract.extension.ipc import IIPCExtension


class MyIPCExtension(IIPCExtension):
    """Custom implementation of IIPCExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    @property
    def ipc_commands(self) -> list[str]:
        """Get the list of IPC commands processed by this extension."""
        return ["ping", "status"]

    async def process_ipc_command(self, payload: dict) -> None:
        """Process an IPC command."""
        print(f"Processing IPC command: {payload}")
        # Implement command processing logic here
```

### Message Handler (MH) Extensions

Message Handler extensions process non-textual input such as images or audio. Implement the `IMHExtension` interface to create a Message Handler extension.

**Setup Code:**

```python
"""Provides an implementation for IMHExtension."""

__all__ = ["MyMHExtension"]

from mugen.core.contract.extension.mh import IMHExtension


class MyMHExtension(IMHExtension):
    """Custom implementation of IMHExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    @property
    def message_types(self) -> list[str]:
        """Get the list of message types handled by this extension."""
        return ["image", "audio"]

    async def handle_message(
        self,
        room_id: str,
        sender: str,
        message: dict
    ) -> None:
        """Handle a message."""
        print(f"Message from {sender} in room {room_id}: {message}")
        # Implement message handling logic here
```

### Context (CTX) Extensions

Context extensions provide additional context to the language model during conversations. Implement the `ICTXExtension` interface to create a Context extension.

**Setup Code:**

```python
"""Provides an implementation for ICTXExtension."""

__all__ = ["MyCTXExtension"]

from mugen.core.contract.extension.ctx import ICTXExtension


class MyCTXExtension(ICTXExtension):
    """Custom implementation of ICTXExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    def get_context(self, user_id: str) -> list[dict]:
        """Provide additional context for a given user."""
        print(f"Fetching context for user ID: {user_id}")
        # Return contextual information here
        return [
            {
                "role": "system",
                "content": "User-specific context",
            }
        ]
```

### Retrieval Augmented Generation (RAG) Extensions

RAG extensions enable dynamic knowledge retrieval to augment LLM responses. Implement the `IRAGExtension` interface to create a RAG extension.

**Setup Code:**

```python
"""Provides an implementation for IRAGExtension."""

__all__ = ["MyRAGExtension"]

from mugen.core.contract.extension.rag import IRAGExtension


class MyRAGExtension(IRAGExtension):
    """Custom implementation of IRAGExtension."""

    _cache_key: str = "ext_cache_key"

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    @property
    def cache_key(self) -> str:
        """Get the key used to access the provider cache."""
        return self._cache_key

    async def retrieve(self, sender: str, message: str) -> None:
        """Perform knowledge retrieval based on the message."""
        print(f"Retrieving knowledge for sender {sender}: {message}")
        # Implement retrieval logic here
```

### Response Pre-processor (RPP) Extensions

RPP extensions modify LLM responses before they are sent to the user. Implement the `IRPPExtension` interface to create an RPP extension.

**Setup Code:**

```python
"""Provides an implementation for IRPPExtension."""

__all__ = ["MyRPPExtension"]

from mugen.core.contract.extension.rpp import IRPPExtension


class MyRPPExtension(IRPPExtension):
    """Custom implementation of IRPPExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    async def preprocess_response(self, room_id: str, user_id: str) -> str:
        """Modify the assistant response before it is delivered."""
        print(f"Preprocessing response for user {user_id} in room {room_id}")
        # Implement response preprocessing logic here
        return "Modified response"
```

### Conversational Trigger (CT) Extensions

CT extensions detect cues in messages and trigger actions based on those cues. Implement the `ICTExtension` interface to create a CT extension.

**Setup Code:**

```python
"""Provides an implementation for ICTExtension."""

__all__ = ["MyCTExtension"]

from mugen.core.contract.extension.ct import ICTExtension


class MyCTExtension(ICTExtension):
    """Custom implementation of ICTExtension."""

    @property
    def platforms(self) -> list[str]:
        """Get the platforms this extension supports."""
        return []

    @property
    def triggers(self) -> list[str]:
        """Get the list of triggers that activate the service."""
        return ["help", "support"]

    async def process_message(
        self, message: str, role: str, room_id: str, user_id: str
    ) -> None:
        """Process message to detect and respond to conversational triggers."""
        print(f"Processing message from {user_id} in room {room_id}: {message}")
        # Implement trigger processing logic here
```

## Next Steps

You are now equipped with the knowledge to effectively extend muGen. To continue learning:

- Check out our guides on working with [clients](clients.md), [gateways](gateways.md), and [services](services.md).
- Learn how to [configure logging](logging.md) to better debug your extensions.
- Explore our [troubleshooting guide](troubleshooting.md) for common issues and solutions.
