import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
from anthropic.types import Message
from langsmith import traceable

from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm.base import StreamEvent
from nafas_core.interfaces.llm.claude import trace_outputs

# Output budgets in the codebase are sized for Claude, which answers at once.
# Local models such as gemma4 reason before answering, inside the same budget:
# a classifier's 64 tokens are spent thinking and the answer comes back empty.
# The floor only raises a ceiling; short answers stay short.
MIN_OUTPUT_TOKENS = 1024


class OllamaLLM:
    """Adapter for Ollama's OpenAI-compatible chat endpoint."""

    def __init__(self, base_url: str, api_key: str = "ollama", client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=300.0,
        )

    async def create(self, **params: Any) -> Message:
        """One chat completion, recorded as a LangSmith LLM run when tracing is on."""
        return await _traced_create(self._create, params, langsmith_extra={"metadata": _trace_metadata(params)})

    async def stream(self, **params: Any) -> AsyncIterator[StreamEvent]:
        """
        Text as the model writes it, then the whole message, tool calls
        included: tool calls arrive in pieces (a name, then fragments of the
        arguments) and are put back together before the final event. Traced
        as one LLM run, timed from the request to the final message.
        """
        if _forced_tool(params):
            # a classifier or gate: enforced structured output, nothing to show as it comes
            yield StreamEvent(message=await self.create(**params))
            return

        async for event in _traced_stream(self._stream, params, langsmith_extra={"metadata": _trace_metadata(params)}):
            yield event

    async def _create(self, **params: Any) -> Message:
        forced = _forced_tool(params)
        body = _structured_body(params, forced) if forced else _request_body(params)
        try:
            response = await self._client.post("/chat/completions", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"local LLM request failed: {exc}") from exc

        try:
            if forced:
                return _message_from_structured(response.json(), forced)
            return _message_from_response(response.json())
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError("local LLM returned an invalid chat response") from exc

    async def _stream(self, **params: Any) -> AsyncIterator[StreamEvent]:
        """The untraced stream of a request that forces no tool (see `stream`)."""
        body = _request_body(params)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        text = ""
        calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        finish_reason = "stop"
        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    usage.update(event.get("usage") or {})
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if piece := delta.get("content"):
                        text += piece
                        yield StreamEvent(text=piece)
                    for call in delta.get("tool_calls") or []:
                        slot = calls.setdefault(call.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                        slot["id"] = call.get("id") or slot["id"]
                        function = call.get("function") or {}
                        slot["name"] = function.get("name") or slot["name"]
                        arguments = function.get("arguments")
                        if isinstance(arguments, dict):
                            slot["arguments"] = json.dumps(arguments)
                        elif arguments:
                            slot["arguments"] += arguments
                    finish_reason = choice.get("finish_reason") or finish_reason
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise LLMError(f"local LLM stream failed: {exc}") from exc

        blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        for index in sorted(calls):
            slot = calls[index]
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise LLMError(f"local LLM streamed unreadable arguments for {slot['name']}") from exc
            blocks.append({"type": "tool_use", "id": slot["id"] or f"call_{index}", "name": slot["name"], "input": arguments})
        if calls:
            finish_reason = "tool_calls"
        yield StreamEvent(message=_message(text, params.get("model", ""), finish_reason, usage, blocks))


def _trace_metadata(params: dict[str, Any]) -> dict[str, Any]:
    # ls_* metadata is how LangSmith knows the provider and model of an LLM run
    return {"ls_provider": "ollama", "ls_model_name": params.get("model")}


def _final_message(events: list[StreamEvent]) -> Message | None:
    """A stream's output for its trace: the whole message it ended with, not every piece of text."""
    return next((event.message for event in reversed(events) if event.message is not None), None)


# The request as the caller wrote it (Anthropic-style) is the run's input; the
# bound method beside it is not worth a trace. Outputs share Claude's shape, so
# token counts land in `usage_metadata` either way.
@traceable(
    run_type="llm",
    name="ChatOllama",
    process_inputs=lambda inputs: inputs["params"],
    process_outputs=trace_outputs,
)
async def _traced_create(call: Callable[..., Awaitable[Message]], params: dict[str, Any]) -> Message:
    return await call(**params)


@traceable(
    run_type="llm",
    name="ChatOllama",
    process_inputs=lambda inputs: inputs["params"],
    reduce_fn=_final_message,
    process_outputs=trace_outputs,
)
async def _traced_stream(call: Callable[..., AsyncIterator[StreamEvent]], params: dict[str, Any]) -> AsyncIterator[StreamEvent]:
    async for event in call(**params):
        yield event


def _request_body(params: dict[str, Any]) -> dict[str, Any]:
    """
    An Anthropic-style request (what every caller writes) as an OpenAI-style
    chat request: the system prompt becomes the first message, content blocks
    become strings, tool calls and results their OpenAI shapes, and tool
    definitions carry `parameters` instead of `input_schema`.
    """
    body = {key: params[key] for key in ("model", "temperature") if key in params}
    if "max_tokens" in params:
        body["max_tokens"] = max(params["max_tokens"], MIN_OUTPUT_TOKENS)
    body["messages"] = _openai_messages(params.get("system"), params.get("messages", []))
    if choice := _tool_choice(params.get("tool_choice")):
        body["tool_choice"] = choice
    if params.get("tools"):
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for tool in params["tools"]
        ]
    return body


def _forced_tool(params: dict[str, Any]) -> dict[str, Any] | None:
    """The tool a caller forces (tool_choice {"type": "tool"}), if any."""
    choice = params.get("tool_choice") or {}
    if choice.get("type") != "tool":
        return None
    return next((t for t in params.get("tools") or [] if t["name"] == choice["name"]), None)


def _structured_body(params: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    """
    A forced tool call as structured output. Ollama does not enforce
    tool_choice: gemma4 answered a forced safety gate in prose two times in
    three, which the gates rightly read as "no verdict" and escalated. A JSON
    schema response format is enforced while decoding, so the answer is the
    tool's arguments every time; the caller still receives a tool call.
    """
    body = _request_body({key: value for key, value in params.items() if key not in ("tools", "tool_choice")})
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": tool["name"], "schema": tool.get("input_schema", {"type": "object"}), "strict": True},
    }
    return body


def _message_from_structured(payload: dict[str, Any], tool: dict[str, Any]) -> Message:
    choice = payload["choices"][0]
    arguments = json.loads(choice["message"].get("content") or "")
    block = {"type": "tool_use", "id": "call_0", "name": tool["name"], "input": arguments}
    return _message("", payload.get("model", ""), "tool_calls", payload.get("usage") or {}, [block])


def _tool_choice(choice: dict[str, Any] | None) -> str | dict[str, Any] | None:
    """Anthropic's tool_choice in OpenAI's terms; a forced call must stay forced, or classifiers answer in prose."""
    match (choice or {}).get("type"):
        case "tool":
            return {"type": "function", "function": {"name": choice["name"]}}
        case "any":
            return "required"
        case "auto":
            return "auto"
        case "none":
            return "none"
    return None


def _block(block: Any) -> dict[str, Any]:
    """A content block as a plain dict, whether the SDK object the agent echoes back or a dict."""
    return block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)


def _text_of(system: Any) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(_block(b).get("text", "") for b in system or [])


def _openai_messages(system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": _text_of(system)})

    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        blocks = [_block(b) for b in content]
        text = "\n".join(b["text"] for b in blocks if b.get("type") == "text" and b.get("text"))
        if role == "assistant":
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)},
                }
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                entry["tool_calls"] = calls
            converted.append(entry)
            continue

        # a user turn: tool results each become a tool message, the rest stays the user's
        for b in blocks:
            if b.get("type") == "tool_result":
                result = b.get("content", "")
                if not isinstance(result, str):
                    result = "\n".join(_block(r).get("text", "") for r in result)
                if b.get("is_error"):
                    result = f"ERROR: {result}"
                converted.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": result})
        if text:
            converted.append({"role": "user", "content": text})

    return converted


def _message_from_response(payload: dict[str, Any]) -> Message:
    choice = payload["choices"][0]
    response_message = choice["message"]
    content = response_message.get("content") or ""
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": content})
    tool_calls = response_message.get("tool_calls") or []
    for index, tool_call in enumerate(tool_calls):
        function = tool_call["function"]
        arguments = function.get("arguments") or "{}"
        blocks.append(
            {
                "type": "tool_use",
                # some servers leave the id out; the loop needs one to pair the result
                "id": tool_call.get("id") or f"call_{index}",
                "name": function["name"],
                "input": json.loads(arguments) if isinstance(arguments, str) else arguments,
            }
        )
    # Ollama does not always report finish_reason "tool_calls": the calls themselves decide
    finish_reason = "tool_calls" if tool_calls else (choice.get("finish_reason") or "stop")
    return _message(content, payload.get("model", ""), finish_reason, payload.get("usage") or {}, blocks)


def _message(
    text: str,
    model: str,
    finish_reason: str,
    usage: dict[str, Any],
    blocks: list[dict[str, Any]] | None = None,
) -> Message:
    stop_reason = "tool_use" if finish_reason == "tool_calls" else "max_tokens" if finish_reason == "length" else "end_turn"
    return Message.model_validate(
        {
            "id": "local-llm",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": blocks if blocks is not None else ([{"type": "text", "text": text}] if text else []),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            },
        }
    )
