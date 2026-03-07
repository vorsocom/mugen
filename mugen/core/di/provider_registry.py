"""Core provider token registry for deterministic DI resolution."""

from __future__ import annotations

from dataclasses import dataclass
import importlib


@dataclass(frozen=True)
class _ProviderTokenSpec:
    module_path: str
    class_name: str


_PROVIDER_TOKEN_REGISTRY: dict[str, dict[str, _ProviderTokenSpec]] = {
    "logging_gateway": {
        "standard": _ProviderTokenSpec(
            module_path="mugen.core.gateway.logging.standard",
            class_name="StandardLoggingGateway",
        ),
    },
    "completion_gateway": {
        "openai": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.openai",
            class_name="OpenAICompletionGateway",
        ),
        "cerebras": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.cerebras",
            class_name="CerebrasCompletionGateway",
        ),
        "sambanova": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.sambanova",
            class_name="SambaNovaCompletionGateway",
        ),
        "groq": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.groqq",
            class_name="GroqCompletionGateway",
        ),
        "bedrock": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.bedrock",
            class_name="BedrockCompletionGateway",
        ),
        "deterministic": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.deterministic",
            class_name="DeterministicCompletionGateway",
        ),
        "vertex": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.vertex",
            class_name="VertexCompletionGateway",
        ),
        "azure_foundry": _ProviderTokenSpec(
            module_path="mugen.core.gateway.completion.azure_foundry",
            class_name="AzureFoundryCompletionGateway",
        ),
    },
    "email_gateway": {
        "smtp": _ProviderTokenSpec(
            module_path="mugen.core.gateway.email.smtp",
            class_name="SMTPEmailGateway",
        ),
        "ses": _ProviderTokenSpec(
            module_path="mugen.core.gateway.email.ses",
            class_name="SESEmailGateway",
        ),
    },
    "sms_gateway": {
        "twilio": _ProviderTokenSpec(
            module_path="mugen.core.gateway.sms.twilio",
            class_name="TwilioSMSGateway",
        ),
    },
    "ipc_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.ipc",
            class_name="DefaultIPCService",
        ),
    },
    "keyval_storage_gateway": {
        "relational": _ProviderTokenSpec(
            module_path="mugen.core.gateway.storage.keyval.relational",
            class_name="RelationalKeyValStorageGateway",
        ),
    },
    "media_storage_gateway": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.gateway.storage.media.provider",
            class_name="DefaultMediaStorageGateway",
        ),
    },
    "relational_storage_gateway": {
        "sqlalchemy": _ProviderTokenSpec(
            module_path="mugen.core.gateway.storage.rdbms.sqla.sqla_gateway",
            class_name="SQLAlchemyRelationalStorageGateway",
        ),
    },
    "web_runtime_store": {
        "relational": _ProviderTokenSpec(
            module_path="mugen.core.gateway.storage.web_runtime.relational_store",
            class_name="RelationalWebRuntimeStore",
        ),
    },
    "nlp_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.nlp",
            class_name="DefaultNLPService",
        ),
    },
    "platform_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.platform",
            class_name="DefaultPlatformService",
        ),
    },
    "user_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.user",
            class_name="DefaultUserService",
        ),
    },
    "context_engine_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.context_engine",
            class_name="DefaultContextEngine",
        ),
    },
    "messaging_service": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.service.messaging",
            class_name="DefaultMessagingService",
        ),
    },
    "knowledge_gateway": {
        "milvus": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.milvus",
            class_name="MilvusKnowledgeGateway",
        ),
        "pinecone": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.pinecone",
            class_name="PineconeKnowledgeGateway",
        ),
        "qdrant": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.qdrant",
            class_name="QdrantKnowledgeGateway",
        ),
        "pgvector": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.pgvector",
            class_name="PgVectorKnowledgeGateway",
        ),
        "chromadb": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.chromadb",
            class_name="ChromaKnowledgeGateway",
        ),
        "weaviate": _ProviderTokenSpec(
            module_path="mugen.core.gateway.knowledge.weaviate",
            class_name="WeaviateKnowledgeGateway",
        ),
    },
    "matrix_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.matrix",
            class_name="MultiProfileMatrixClient",
        ),
    },
    "line_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.line",
            class_name="MultiProfileLineClient",
        ),
    },
    "signal_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.signal",
            class_name="MultiProfileSignalClient",
        ),
    },
    "telegram_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.telegram",
            class_name="MultiProfileTelegramClient",
        ),
    },
    "wechat_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.wechat",
            class_name="MultiProfileWeChatClient",
        ),
    },
    "whatsapp_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.whatsapp",
            class_name="MultiProfileWhatsAppClient",
        ),
    },
    "web_client": {
        "default": _ProviderTokenSpec(
            module_path="mugen.core.client.web",
            class_name="DefaultWebClient",
        ),
    },
}


def resolve_provider_class(
    *,
    provider_name: str,
    token: object,
    interface: type,
) -> type:
    """Resolve provider class from a strict token registry."""
    if not isinstance(token, str):
        raise RuntimeError(
            f"Invalid configuration ({provider_name}): expected provider token string."
        )

    normalized = token.strip().lower()
    if normalized == "":
        raise RuntimeError(
            f"Invalid configuration ({provider_name}): provider token must be non-empty."
        )
    if ":" in normalized:
        raise RuntimeError(
            f"Invalid configuration ({provider_name}): module:Class paths are not supported."
        )

    provider_tokens = _PROVIDER_TOKEN_REGISTRY.get(provider_name, {})
    provider_spec = provider_tokens.get(normalized)
    if provider_spec is None:
        known_tokens = ", ".join(sorted(provider_tokens))
        module_path_hint = ""
        if "." in normalized:
            module_path_hint = (
                " Config values must use provider tokens (for example "
                f"{known_tokens}) rather than Python module paths."
            )
        raise RuntimeError(
            f"Unknown provider token ({provider_name}): {token!r}. "
            f"Known tokens: {known_tokens}.{module_path_hint}"
        )

    try:
        module = importlib.import_module(provider_spec.module_path)
        provider_class = getattr(module, provider_spec.class_name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"Valid subclass not found ({provider_name}).") from exc

    if not isinstance(provider_class, type):
        raise RuntimeError(f"Valid subclass not found ({provider_name}).")
    if not issubclass(provider_class, interface):
        raise RuntimeError(f"Valid subclass not found ({provider_name}).")
    return provider_class
