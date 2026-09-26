from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic.types import Message


@dataclass
class StreamEvent:
    """A piece of a streamed reply: text as it comes, then the whole message once, last."""

    text: str | None = None
    message: Message | None = None


class LLM(Protocol):
    async def create(self, **params: Any) -> Message:
        """
        One Messages API call; `params` are those of `messages.create`.

        Raises LLMRefusalError when the model declines, and LLMError for any
        failure left after the SDK's own retries.
        """
        ...

    def stream(self, **params: Any) -> AsyncIterator[StreamEvent]:
        """
        The same call, streamed: text events as the model writes, then one
        event carrying the final Message (tool calls, usage, stop reason).
        Raises as `create` does.
        """
        ...
