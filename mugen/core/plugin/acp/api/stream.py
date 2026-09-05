"""Keep streaming responses subject to current authorization decisions."""

from collections.abc import AsyncIterator, Awaitable, Callable


async def authorized_stream(
    stream: AsyncIterator[str],
    *,
    permitted: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Recheck access before every replay, live, or keepalive chunk."""
    try:
        async for chunk in stream:
            if not await permitted():
                return
            yield chunk
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
