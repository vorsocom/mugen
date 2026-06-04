"""Stable permission keys for knowledge_pack tenant configuration access."""

KNOWLEDGE_PACK_PERMISSION_NAMESPACE = "com.vorsocomputing.mugen.knowledge_pack"
KNOWLEDGE_PACK_CONFIGURATOR_PERMISSION_NAME = "configurator"
KNOWLEDGE_PACK_CONFIGURATOR_PERMISSION = (
    f"{KNOWLEDGE_PACK_PERMISSION_NAMESPACE}:"
    f"{KNOWLEDGE_PACK_CONFIGURATOR_PERMISSION_NAME}"
)
