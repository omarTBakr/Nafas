import json

import anthropic
import httpx2
import pytest

from nafas_core.exceptions.providers import LLMError, LLMRefusalError
from nafas_core.interfaces.llm.claude import AnthropicLLM
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message


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
