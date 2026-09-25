from collections.abc import Iterable
from typing import Any

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage


def text_message(text: str, model: str = "fake") -> Message:
    """A finished assistant turn holding one text block."""
    return Message(
        id="msg_fake",
        type="message",
        role="assistant",
        model=model,
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=0, output_tokens=0),
    )


def tool_use_message(name: str, tool_input: dict, tool_use_id: str = "toolu_fake", model: str = "fake") -> Message:
    """An assistant turn asking for one tool call."""
    return Message(
        id="msg_fake",
        type="message",
        role="assistant",
        model=model,
        content=[ToolUseBlock(type="tool_use", id=tool_use_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=0, output_tokens=0),
    )


class FakeLLM:
    """
    Replays scripted responses in order and records every request.

    A test scripts what "the model" says, runs the code under test, then
    asserts on `requests` — which prompt, which tools, which model.
    """

    def __init__(self, responses: Iterable[Message | str] = ()):
        self._responses = [text_message(r) if isinstance(r, str) else r for r in responses]
        self.requests: list[dict[str, Any]] = []

    async def create(self, **params: Any) -> Message:
        self.requests.append(params)
        if not self._responses:
            raise AssertionError(f"FakeLLM ran out of scripted responses at call {len(self.requests)}")

        return self._responses.pop(0)
