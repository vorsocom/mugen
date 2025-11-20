"""Provides an implementation of ICTXExtension."""

__all__ = ["SystemPersonaCTXExtension"]

from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core import di


# pylint: disable=too-few-public-methods
class SystemPersonaCTXExtension(ICTXExtension):
    """An implementation of ICTXExtension to provide system persona."""

    _config = di.container.config

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return []

    def get_context(self, user_id: str) -> list[dict]:
        context = []
        if hasattr(self._config.mugen, "assistant"):
            if hasattr(self._config.mugen.assistant, "persona"):
                if len(self._config.mugen.assistant.persona) > 0:
                    context.append(
                        {
                            "role": "system",
                            "content": self._config.mugen.assistant.persona,
                        }
                    )

        return context
