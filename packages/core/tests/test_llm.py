import json

import anthropic
import httpx
import httpx2
import pytest

from nafas_core.exceptions.providers import LLMError, LLMRefusalError
from nafas_core.interfaces.llm.claude import AnthropicLLM
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.llm.ollama import OllamaLLM


def claude_with(handler) -> AnthropicLLM:
    """The real adapter and SDK, with HTTP answered by `handler` instead of the API."""
    client = anthropic.AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicLLM(api_key="test", client=client)


def test_a_workspace_id_is_sent_on_every_request():
    llm = AnthropicLLM(api_key="test", workspace_id="wrkspc_123")

    assert llm._client.default_headers["anthropic-workspace-id"] == "wrkspc_123"


def test_no_workspace_header_without_a_workspace():
    assert "anthropic-workspace-id" not in AnthropicLLM(api_key="test")._client.default_headers


def test_a_failed_call_traces_no_output_instead_of_crashing():
    from nafas_core.interfaces.llm.claude import trace_outputs

    assert trace_outputs(None) == {}


def message_body(stop_reason: str, text: str = "hi", stop_details: dict | None = None) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


async def test_a_normal_reply_comes_back_as_a_message():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message_body("end_turn", "مرحبا"))

    response = await claude_with(handler).create(
        model="claude-sonnet-5", max_tokens=100, messages=[{"role": "user", "content": "hello"}]
    )

    assert response.content[0].text == "مرحبا"
    assert seen["body"]["model"] == "claude-sonnet-5"


async def test_a_refusal_raises_instead_of_returning_empty_content():
    def handler(request):
        return httpx2.Response(200, json=message_body("refusal", "", {"type": "refusal", "category": "bio", "explanation": None}))

    with pytest.raises(LLMRefusalError, match="bio"):
        await claude_with(handler).create(model="claude-sonnet-5", max_tokens=100, messages=[])


async def test_an_api_error_becomes_an_llm_error():
    def handler(request):
        return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}})

    with pytest.raises(LLMError, match="400"):
        await claude_with(handler).create(model="claude-sonnet-5", max_tokens=100, messages=[])


async def test_local_ollama_adapter_preserves_the_llm_message_contract():
    async def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "model": "gemma4",
                "choices": [{"message": {"role": "assistant", "content": "مرحبا"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url="http://llm/v1", transport=transport)
    llm = OllamaLLM("http://llm/v1", client=client)

    response = await llm.create(model="gemma4", max_tokens=100, messages=[{"role": "user", "content": "hello"}])

    assert response.content[0].text == "مرحبا"
    assert response.usage.input_tokens == 4


def ollama_capturing(reply: dict) -> tuple[OllamaLLM, list[dict]]:
    """An Ollama adapter whose server records each request body and answers `reply`."""
    seen: list[dict] = []

    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "gemma4", "usage": {}, "choices": [reply]})

    client = httpx.AsyncClient(base_url="http://llm/v1", transport=httpx.MockTransport(handler))
    return OllamaLLM("http://llm/v1", client=client), seen


async def test_ollama_receives_the_system_prompt_as_its_first_message():
    llm, seen = ollama_capturing({"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"})

    await llm.create(model="gemma4", system="Answer with one intent.", messages=[{"role": "user", "content": "hi"}])

    assert seen[0]["messages"][0] == {"role": "system", "content": "Answer with one intent."}


async def test_ollama_gets_tools_in_openai_shape():
    llm, seen = ollama_capturing({"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"})
    tool = {
        "name": "hold",
        "description": "Reserve a time",
        "input_schema": {"type": "object", "properties": {"start": {"type": "string"}}},
    }

    await llm.create(model="gemma4", tools=[tool], messages=[{"role": "user", "content": "hi"}])

    function = seen[0]["tools"][0]["function"]
    assert function["name"] == "hold" and function["parameters"]["properties"] == {"start": {"type": "string"}}
    assert "input_schema" not in function


async def test_a_tool_round_trip_with_sdk_blocks_translates_instead_of_crashing():
    """The agent echoes the model's turn back as SDK objects; that crashed JSON encoding."""
    from anthropic.types import TextBlock, ToolUseBlock

    llm, seen = ollama_capturing(
        {"message": {"role": "assistant", "content": "Thursday 18:00 is free."}, "finish_reason": "stop"}
    )
    history = [
        {"role": "user", "content": "is thursday at 6 free?"},
        {
            "role": "assistant",
            "content": [
                TextBlock(type="text", text="Let me check."),
                ToolUseBlock(type="tool_use", id="call_0", name="interpret_time", input={"day": {"weekday": 3}, "hour": 6}),
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_0", "content": '{"bookable": true}', "is_error": False}],
        },
    ]

    reply = await llm.create(model="gemma4", messages=history)

    sent = seen[0]["messages"]
    assert sent[1]["tool_calls"][0]["function"] == {"name": "interpret_time", "arguments": '{"day": {"weekday": 3}, "hour": 6}'}
    assert sent[1]["content"] == "Let me check."
    assert sent[2] == {"role": "tool", "tool_call_id": "call_0", "content": '{"bookable": true}'}
    assert reply.content[0].text == "Thursday 18:00 is free."


async def test_an_ollama_tool_call_is_a_tool_use_even_without_the_finish_reason():
    llm, _ = ollama_capturing(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "my_appointments", "arguments": "{}"}}],
            },
            "finish_reason": "stop",
        }
    )

    reply = await llm.create(model="gemma4", messages=[{"role": "user", "content": "my appointments?"}])

    assert reply.stop_reason == "tool_use"
    assert (reply.content[0].type, reply.content[0].name, reply.content[0].id) == ("tool_use", "my_appointments", "call_0")


async def test_a_forced_tool_becomes_enforced_structured_output():
    """
    Ollama does not enforce tool_choice: gemma4 answered a forced safety gate in
    prose 2 times in 3. A JSON schema response format is enforced while
    decoding, and the caller still gets its tool call. Small budgets also get
    room to think first (a 64-token classifier came back empty).
    """
    from nafas_core.interfaces.llm.ollama import MIN_OUTPUT_TOKENS

    schema = {"type": "object", "properties": {"sensitive": {"type": "boolean"}}, "required": ["sensitive"]}
    llm, seen = ollama_capturing(
        {"message": {"role": "assistant", "content": '{\n "sensitive": false\n}\n'}, "finish_reason": "stop"}
    )

    reply = await llm.create(
        model="gemma4",
        max_tokens=64,
        tools=[{"name": "record_sensitivity", "input_schema": schema}],
        tool_choice={"type": "tool", "name": "record_sensitivity"},
        messages=[{"role": "user", "content": "what foods lower blood pressure?"}],
    )

    sent = seen[0]
    assert sent["response_format"]["json_schema"] == {"name": "record_sensitivity", "schema": schema, "strict": True}
    assert "tools" not in sent and "tool_choice" not in sent
    assert sent["max_tokens"] == MIN_OUTPUT_TOKENS
    assert reply.stop_reason == "tool_use"
    assert (reply.content[0].name, reply.content[0].input) == ("record_sensitivity", {"sensitive": False})


async def test_an_unforced_tool_choice_is_passed_through():
    llm, seen = ollama_capturing({"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"})

    await llm.create(
        model="gemma4",
        tools=[{"name": "classify", "input_schema": {"type": "object", "properties": {}}}],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": "hi"}],
    )

    assert seen[0]["tool_choice"] == "required"


async def test_structured_output_that_is_not_json_is_an_llm_error_not_a_crash():
    llm, _ = ollama_capturing({"message": {"role": "assistant", "content": "not json"}, "finish_reason": "stop"})

    with pytest.raises(LLMError):
        await llm.create(
            model="gemma4",
            tools=[{"name": "t", "input_schema": {"type": "object"}}],
            tool_choice={"type": "tool", "name": "t"},
            messages=[{"role": "user", "content": "hi"}],
        )


async def test_the_fake_replays_in_order_and_records_requests():
    llm = FakeLLM(["first", tool_use_message("find_slots", {"day": "2026-10-01"})])

    first = await llm.create(model="m", messages=[{"role": "user", "content": "a"}])
    second = await llm.create(model="m", messages=[{"role": "user", "content": "b"}])

    assert first.content[0].text == "first"
    assert second.stop_reason == "tool_use"
    assert second.content[0].input == {"day": "2026-10-01"}
    assert [r["messages"][0]["content"] for r in llm.requests] == ["a", "b"]


async def test_the_fake_fails_loudly_when_the_script_runs_out():
    with pytest.raises(AssertionError, match="ran out"):
        await FakeLLM().create(model="m", messages=[])


async def test_calls_are_traced_as_llm_runs_with_usage(monkeypatch):
    """With tracing on, each call reaches LangSmith as an LLM run carrying model and token counts."""
    from unittest.mock import MagicMock

    import langsmith
    from langsmith.run_helpers import tracing_context

    runs = []
    ls_client = MagicMock(spec=langsmith.Client)
    ls_client.create_run.side_effect = lambda **run: runs.append(run)
    ls_client.update_run.side_effect = lambda run_id, **update: runs.append(update)

    def handler(request):
        body = message_body("end_turn")
        body["usage"] = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 90}
        return httpx2.Response(200, json=body)

    with tracing_context(enabled=True, client=ls_client, project_name="nafas-test"):
        await claude_with(handler).create(model="claude-sonnet-5", max_tokens=100, messages=[{"role": "user", "content": "x"}])

    posted = {k: v for run in runs for k, v in run.items() if v is not None}
    assert posted["run_type"] == "llm"
    assert posted["inputs"]["model"] == "claude-sonnet-5"
    assert "client" not in posted["inputs"]
    assert posted["extra"]["metadata"]["ls_model_name"] == "claude-sonnet-5"
    assert posted["outputs"]["usage_metadata"]["input_tokens"] == 100
    assert posted["outputs"]["usage_metadata"]["total_tokens"] == 105


def sse_stream(pieces: list[str]) -> bytes:
    """A streamed reply as the Messages API sends it."""
    start = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 1},
    }
    end = {"stop_reason": "end_turn", "stop_sequence": None}
    events = [
        ("message_start", {"type": "message_start", "message": start}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        *[
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}})
            for piece in pieces
        ],
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": end, "usage": {"output_tokens": 7}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events).encode()


async def test_a_streamed_reply_arrives_in_pieces_then_as_a_whole_message():
    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx2.Response(200, content=sse_stream(["مرحبا ", "يا ", "دكتور"]), headers={"content-type": "text/event-stream"})

    events = [e async for e in claude_with(handler).stream(model="claude-sonnet-5", max_tokens=100, messages=[])]

    assert [e.text for e in events[:-1]] == ["مرحبا ", "يا ", "دكتور"]
    final = events[-1].message
    assert final.content[0].text == "مرحبا يا دكتور" and final.stop_reason == "end_turn"
    assert (final.usage.input_tokens, final.usage.output_tokens) == (12, 7)


async def test_a_stream_that_fails_becomes_an_llm_error():
    def handler(request):
        return httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})

    with pytest.raises(LLMError):
        async for _ in claude_with(handler).stream(model="claude-sonnet-5", max_tokens=100, messages=[]):
            pass
