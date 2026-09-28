"""
The booking assistant's turn: Claude with tools, looped until it answers.

The loop owns nothing but the conversation with the model; every fact about
the calendar comes from BookingTools, so a test can script the model and
fake the tools, and the real tools can be swapped without touching this.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from anthropic.types import Message

from nafas_core.clients.base import UpstreamRefusal
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger
from nafas_core.tracing import step

logger = get_logger(__name__)

# enough for interpret → hold → reply with room for a correction; a loop that
# goes further is stuck, and the patient gets an apology instead of a bill
MAX_STEPS = 8

# sent to the model, once, when it ends a turn without a word for the patient
EMPTY_ANSWER_NUDGE = "(Reply to the patient now, in words, about what you just did or found.)"
MAX_TOKENS = 2048


class BookingTools(Protocol):
    async def interpret_time(self, expression: dict) -> dict: ...

    async def hold(self, start: str, reason_for_visit: str | None) -> dict: ...

    async def confirm(self, appointment_id: str) -> dict: ...

    async def cancel(self, appointment_id: str) -> dict: ...

    async def my_appointments(self) -> list[dict]: ...


@dataclass
class AgentReply:
    text: str
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    # what changed in the calendar this turn, for the UI to show as cards
    actions: list[dict] = field(default_factory=list)


@step("conversation.booking_tool", run_type="tool")
async def _run_tool(tools: BookingTools, name: str, arguments: dict, actions: list[dict]) -> tuple[Any, bool]:
    """(result, is_error). A refusal is a result the model must read and explain, not a crash."""
    try:
        match name:
            case "interpret_time":
                return await tools.interpret_time(arguments), False
            case "hold":
                held = await tools.hold(arguments["start"], arguments.get("reason_for_visit"))
                actions.append({"type": "hold", "appointment": held})
                return held, False
            case "confirm":
                confirmed = await tools.confirm(arguments["appointment_id"])
                actions.append({"type": "confirmed", "appointment": confirmed})
                return confirmed, False
            case "cancel":
                cancelled = await tools.cancel(arguments["appointment_id"])
                actions.append({"type": "cancelled", "appointment": cancelled})
                return cancelled, False
            case "my_appointments":
                return await tools.my_appointments(), False
            case _:
                return {"error": f"no tool named {name}"}, True
    except UpstreamRefusal as refusal:
        return refusal.body, True
    except ValueError as bad:
        # an argument the model wrote that does not parse (a malformed time):
        # the model reads why and can ask or correct, the turn goes on
        return {"error": f"invalid argument: {bad}"}, True
    except KeyError as missing:
        return {"error": f"missing argument {missing}"}, True


@step("conversation.booking_agent")
async def _streamed(llm: LLM, params: dict, on_text: Callable[[str], Awaitable[None]]) -> Message:
    """One model call streamed: text to `on_text` as it comes, the whole message back at the end."""
    final: Message | None = None
    async for event in llm.stream(**params):
        if event.text:
            await on_text(event.text)
        if event.message is not None:
            final = event.message
    if final is None:
        raise LLMError("the stream ended without a final message")
    return final


async def run_booking_turn(
    llm: LLM,
    tools: BookingTools,
    *,
    model: str,
    system: str,
    tool_definitions: list[dict],
    prompt_version: str,
    history: list[dict],
    apology: str,
    on_text: Callable[[str], Awaitable[None]] | None = None,
) -> AgentReply:
    """
    One patient turn. `history` ends with the patient's new message. Returns
    the assistant's reply and what it did; never raises for a model failure
    — the patient gets `apology`, and the log gets the reason.

    With `on_text`, every model call is streamed and each piece of text is
    handed to it as it is written, so the patient watches the reply appear.
    The returned reply stays the authority: it is what is stored, and what
    replaces the streamed text when the turn ends (an apology, for instance).
    """
    messages = list(history)
    actions: list[dict] = []
    tokens_in = tokens_out = 0

    nudged = False
    for _ in range(MAX_STEPS):
        try:
            params = {
                "model": model,
                "system": system,
                "tools": tool_definitions,
                "messages": messages,
                "max_tokens": MAX_TOKENS,
            }
            response = await (_streamed(llm, params, on_text) if on_text else llm.create(**params))
        except LLMError as exc:
            logger.error("booking turn failed at the model: %s", exc)
            return AgentReply(apology, model, prompt_version, tokens_in, tokens_out, actions)

        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text").strip()
            if text:
                return AgentReply(text, response.model, prompt_version, tokens_in, tokens_out, actions)
            # Local models sometimes end a turn with nothing to say, often right
            # after a tool result. Ask once for the reply in words; the nudge is
            # sent to the model only and never stored in the conversation.
            logger.warning(
                "booking turn: empty answer (stop_reason=%s, actions=%s)%s",
                response.stop_reason,
                [a["type"] for a in actions],
                "" if nudged else "; asking once more",
            )
            if nudged:
                return AgentReply(apology, response.model, prompt_version, tokens_in, tokens_out, actions)
            nudged = True
            messages.append({"role": "user", "content": EMPTY_ANSWER_NUDGE})
            continue

        # the whole assistant turn goes back, thinking and tool calls included
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result, is_error = await _run_tool(tools, block.name, dict(block.input), actions)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                    "is_error": is_error,
                }
            )
        # every result of one turn in a single message
        messages.append({"role": "user", "content": results})

    logger.error("booking turn gave up after %d steps", MAX_STEPS)
    return AgentReply(apology, model, prompt_version, tokens_in, tokens_out, actions)
