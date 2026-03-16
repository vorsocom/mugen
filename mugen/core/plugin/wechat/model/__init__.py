"""WeChat persistence models."""

__all__ = [
    "WeChatEventDedup",
    "WeChatEventDeadLetter",
]

from mugen.core.plugin.wechat.model.event_dedup import WeChatEventDedup
from mugen.core.plugin.wechat.model.event_dead_letter import WeChatEventDeadLetter
