"""
The doctor's chat turn, streamed: text as the model writes it, a note when it
reaches for a tool, and a last event with what produced the answer.
"""

import json
from collections.abc import AsyncIterator

from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger
from nafas_core.tracing import step

logger = get_logger(__name__)

MAX_STEPS = 6
MAX_TOKENS = 1500


@step("doctor_assistant.chat")
async def run_doctor_chat(
    llm: LLM, tools, *, model: str, system: str, tool_definitions: list[dict], prompt_version: str, history: list[dict]
) -> AsyncIterator[dict]:
    """Events: {"type": "text", "text"}, {"type": "tool", "name"}, {"type": "error", "detail"}, then {"type": "done", ...}."""
    messages = list(history)
    tokens_in = tokens_out = 0
    for _ in range(MAX_STEPS):
        final = None
        try:
            async for event in llm.stream(
                model=model, system=system, tools=tool_definitions, messages=messages, max_tokens=MAX_TOKENS
            ):
                if event.text:
                    yield {"type": "text", "text": event.text}
                if event.message is not None:
                    final = event.message
        except LLMError as exc:
            logger.error("doctor chat failed at the model: %s", exc)
            yield {"type": "error", "detail": "the assistant is unavailable; try again shortly"}
            return

        tokens_in += final.usage.input_tokens
        tokens_out += final.usage.output_tokens
        if final.stop_reason != "tool_use":
            yield {
                "type": "done",
                "model": final.model,
                "prompt_version": prompt_version,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
            return

        messages.append({"role": "assistant", "content": final.content})
        results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name}
            try:
                result, is_error = await tools.run(block.name, dict(block.input)), False
            except Exception:
                logger.exception("doctor tool %s failed", block.name)
                result, is_error = {"error": "that record could not be read just now"}, True
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    yield {"type": "error", "detail": "the assistant could not finish; ask a narrower question"}
