from typing import Any, Protocol

from anthropic.types import Message


class LLM(Protocol):
    async def create(self, **params: Any) -> Message:
        """
        One Messages API call; `params` are those of `messages.create`.

        Raises LLMRefusalError when the model declines, and LLMError for any
        failure left after the SDK's own retries.
        """
        ...
