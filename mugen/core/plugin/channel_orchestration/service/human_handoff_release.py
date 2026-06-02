"""Registry for downstream human handoff release hooks."""

from __future__ import annotations

__all__ = ["HumanHandoffReleaseHookRegistry"]

from dataclasses import dataclass
import uuid

from mugen.core.plugin.channel_orchestration.contract.service import (
    HumanHandoffReleased,
    IHumanHandoffReleaseHandler,
)


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_platform(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return normalized.lower()


def _normalize_uuid(value: object) -> uuid.UUID | None:
    if value in [None, ""]:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


@dataclass(frozen=True, slots=True)
class _ReleaseHookBinding:
    handler: IHumanHandoffReleaseHandler
    service_route_key: str | None
    platform: str | None
    client_profile_id: uuid.UUID | None
    index: int

    @property
    def specificity(self) -> int:
        return sum(
            item is not None
            for item in (
                self.service_route_key,
                self.platform,
                self.client_profile_id,
            )
        )


class HumanHandoffReleaseHookRegistry:
    """Selects one downstream hook for a released human handoff session."""

    def __init__(self) -> None:
        self._bindings: list[_ReleaseHookBinding] = []

    def register_handler(
        self,
        handler: IHumanHandoffReleaseHandler,
        *,
        service_route_key: str | None = None,
        platform: str | None = None,
        client_profile_id: uuid.UUID | str | None = None,
    ) -> None:
        """Register a downstream handler for matching release events."""
        handler_method = getattr(handler, "on_handoff_released", None)
        if not callable(handler_method):
            raise TypeError("handler must define on_handoff_released.")

        self._bindings.append(
            _ReleaseHookBinding(
                handler=handler,
                service_route_key=_normalize_optional_text(service_route_key),
                platform=_normalize_platform(platform),
                client_profile_id=_normalize_uuid(client_profile_id),
                index=len(self._bindings),
            )
        )

    @staticmethod
    def _matches(binding: _ReleaseHookBinding, event: HumanHandoffReleased) -> bool:
        session = event.session
        if binding.platform is not None and binding.platform != _normalize_platform(
            session.platform
        ):
            return False
        if (
            binding.client_profile_id is not None
            and binding.client_profile_id != session.client_profile_id
        ):
            return False
        return True

    def select_handler(
        self,
        event: HumanHandoffReleased,
    ) -> IHumanHandoffReleaseHandler | None:
        """Return the single best matching release handler, if any."""
        route_key = _normalize_optional_text(event.session.service_route_key)
        if route_key is not None:
            route_candidates = sorted(
                (
                    binding
                    for binding in self._bindings
                    if binding.service_route_key == route_key
                    and self._matches(binding, event)
                ),
                key=lambda item: (-item.specificity, item.index),
            )
            if route_candidates:
                return route_candidates[0].handler

        fallback_candidates = sorted(
            (
                binding
                for binding in self._bindings
                if binding.service_route_key is None and self._matches(binding, event)
            ),
            key=lambda item: (-item.specificity, item.index),
        )
        if fallback_candidates:
            return fallback_candidates[0].handler
        return None

    async def notify_release(self, event: HumanHandoffReleased) -> str:
        """Invoke the selected release handler and return the hook decision."""
        handler = self.select_handler(event)
        if handler is None:
            return "skipped"
        await handler.on_handoff_released(event)
        return "sent"
