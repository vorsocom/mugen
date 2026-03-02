"""Provides an implementation of ICTXExtension."""

__all__ = ["SystemPersonaCTXExtension"]

from types import SimpleNamespace

from mugen.core.contract.extension.ctx import ICTXExtension


# pylint: disable=too-few-public-methods
class SystemPersonaCTXExtension(ICTXExtension):
    """An implementation of ICTXExtension to provide system persona."""

    def __init__(self, config: SimpleNamespace) -> None:
        self._config = config

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
