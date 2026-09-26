from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic.types import Message
from langsmith import traceable

from nafas_core.exceptions.providers import LLMError, LLMRefusalError
from nafas_core.interfaces.llm.base import StreamEvent
from nafas_core.logger import get_logger

logger = get_logger(__name__)


def trace_outputs(message: Message | None) -> dict:
    """
    A Message as LangSmith wants an LLM run's outputs: token counts under
    `usage_metadata`, which is what its cost and token views read.

    Anthropic reports cache reads and writes *beside* input_tokens rather than
    inside them, so they are added in; otherwise cached calls look cheaper
    than they were.
    """
    if message is None:
        # the call raised; the trace records the error, and there is no output
        return {}

    outputs = message.model_dump(mode="json")
    usage = outputs.pop("usage", None) or {}

    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    input_tokens = (usage.get("input_tokens") or 0) + cache_read + cache_write
    output_tokens = usage.get("output_tokens") or 0

    outputs["usage_metadata"] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_token_details": {"cache_read": cache_read, "cache_creation": cache_write},
    }

    return outputs


# langsmith's wrap_anthropic would do this, but as of langsmith 0.14.1 it
# patches `client.completions`, which anthropic 1.x removed, and raises on
# construction. Tracing the one call we make is all it did for us anyway.
@traceable(
    run_type="llm",
    name="ChatAnthropic",
    # the request is the input; the SDK client beside it is not worth a trace
    process_inputs=lambda inputs: inputs["params"],
    process_outputs=trace_outputs,
)
async def _traced_create(client: anthropic.AsyncAnthropic, params: dict[str, Any]) -> Message:
    return await client.messages.create(**params)


class AnthropicLLM:
    """
    Claude through the official async SDK, traced by LangSmith.

    Every call is recorded as an LLM run when LANGSMITH_TRACING is true (see
    utils.tracing); with tracing off, `traceable` is a pass-through.
    """

    def __init__(self, api_key: str, workspace_id: str = "", client: anthropic.AsyncAnthropic | None = None):
        # a key not scoped to one workspace must name the workspace on every request
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key or None, default_headers=headers)

    async def create(self, **params: Any) -> Message:
        # ls_* metadata is how LangSmith knows the provider and model for pricing
        trace_metadata = {"ls_provider": "anthropic", "ls_model_name": params.get("model")}

        try:
            response = await _traced_create(self._client, params, langsmith_extra={"metadata": trace_metadata})
        except anthropic.APIStatusError as exc:
            # 4xx other than 408/409/429 is a bug in the request, 5xx outlived
            # the SDK's retries; either way the caller cannot fix it by retrying
            logger.error("claude call failed: %s (request %s)", exc.status_code, exc.request_id)
            raise LLMError(f"Claude returned {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"could not reach Claude: {exc}") from exc

        _refused(response)
        return response

    async def stream(self, **params: Any) -> AsyncIterator[StreamEvent]:
        """Text as Claude writes it, then the final message, traced as one LLM run like `create`."""
        final: Message | None = None
        try:
            async with self._client.messages.stream(**params) as streamed:
                async for text in streamed.text_stream:
                    yield StreamEvent(text=text)
                final = await streamed.get_final_message()
        except anthropic.APIStatusError as exc:
            logger.error("claude stream failed: %s (request %s)", exc.status_code, exc.request_id)
            raise LLMError(f"Claude returned {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"could not reach Claude: {exc}") from exc
        finally:
            _trace_stream(params, final)

        _refused(final)
        yield StreamEvent(message=final)


def _refused(response: Message) -> None:
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise LLMRefusalError(f"Claude declined the request (category {category})")


@traceable(run_type="llm", name="ChatAnthropic", process_outputs=trace_outputs)
def _trace_stream(params: dict[str, Any], message: Message | None) -> Message | None:
    """Records a finished stream as the LLM run it was: the request in, the final message out."""
    return message
