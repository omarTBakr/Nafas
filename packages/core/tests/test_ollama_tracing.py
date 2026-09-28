"""The local model's calls reach LangSmith as LLM runs, as Claude's do, nested under the pipeline step that made them."""

import json
from unittest.mock import MagicMock

import httpx
import langsmith
from langsmith.run_helpers import tracing_context

from nafas_core.interfaces.llm.ollama import OllamaLLM
from nafas_core.tracing import step

REQUEST = {"model": "gemma4:e4b", "max_tokens": 64, "messages": [{"role": "user", "content": "hello"}]}


def recording_client() -> tuple[MagicMock, list[dict]]:
    """A LangSmith client that keeps what would have been posted, one dict per create or update."""
    posted: list[dict] = []
    client = MagicMock(spec=langsmith.Client)
    client.create_run.side_effect = lambda **run: posted.append(run)
    client.update_run.side_effect = lambda run_id, **update: posted.append({"id": run_id, **update})
    return client, posted


def runs(posted: list[dict]) -> dict:
    """Creates and updates merged per run id, in the order the runs started."""
    merged: dict = {}
    for event in posted:
        merged.setdefault(event["id"], {}).update({k: v for k, v in event.items() if v is not None})
    return merged


def ollama(handler) -> OllamaLLM:
    client = httpx.AsyncClient(base_url="http://llm/v1", transport=httpx.MockTransport(handler))
    return OllamaLLM("http://llm/v1", client=client)


def reply(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gemma4:e4b",
            "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
    )


def streamed_reply(request: httpx.Request) -> httpx.Response:
    chunks = [
        {"choices": [{"delta": {"content": "hel"}}]},
        {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def assert_llm_run(run: dict, input_tokens: int, output_tokens: int) -> None:
    assert run["run_type"] == "llm"
    assert run["name"] == "ChatOllama"
    assert run["inputs"]["model"] == "gemma4:e4b"
    assert run["inputs"]["messages"] == REQUEST["messages"]
    assert "call" not in run["inputs"]
    assert run["extra"]["metadata"]["ls_provider"] == "ollama"
    assert run["extra"]["metadata"]["ls_model_name"] == "gemma4:e4b"
    usage = run["outputs"]["usage_metadata"]
    assert (usage["input_tokens"], usage["output_tokens"]) == (input_tokens, output_tokens)
    assert usage["total_tokens"] == input_tokens + output_tokens


async def test_a_local_call_is_traced_as_an_llm_run_with_usage():
    client, posted = recording_client()

    with tracing_context(enabled=True, client=client, project_name="nafas-test"):
        message = await ollama(reply).create(**REQUEST)

    assert message.content[0].text == "hi"
    [run] = runs(posted).values()
    assert_llm_run(run, 7, 3)
    assert run["outputs"]["content"][0]["text"] == "hi"


async def test_a_local_stream_is_traced_as_one_llm_run_with_the_whole_message():
    client, posted = recording_client()

    with tracing_context(enabled=True, client=client, project_name="nafas-test"):
        events = [event async for event in ollama(streamed_reply).stream(**REQUEST)]

    assert [e.text for e in events if e.text] == ["hel", "lo"]
    assert events[-1].message.content[0].text == "hello"
    [run] = runs(posted).values()
    assert_llm_run(run, 9, 2)
    assert run["outputs"]["content"][0]["text"] == "hello"


async def test_a_forced_tool_streamed_is_one_run_not_two():
    def structured(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gemma4:e4b",
                "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        )

    tool = {"name": "verdict", "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}
    client, posted = recording_client()

    with tracing_context(enabled=True, client=client, project_name="nafas-test"):
        events = [
            e async for e in ollama(structured).stream(**REQUEST, tools=[tool], tool_choice={"type": "tool", "name": "verdict"})
        ]

    assert events[-1].message.content[0].input == {"ok": True}
    [run] = runs(posted).values()
    assert_llm_run(run, 5, 1)


async def test_model_calls_nest_under_the_pipeline_step_that_made_them():
    client, posted = recording_client()
    llm = ollama(reply)

    @step("conversation.turn")
    async def turn(question: str) -> str:
        first = await llm.create(**REQUEST)
        streamed = [e async for e in ollama(streamed_reply).stream(**REQUEST)]
        return first.content[0].text + streamed[-1].message.content[0].text

    with tracing_context(enabled=True, client=client, project_name="nafas-test"):
        assert await turn("hello") == "hihello"

    parent, *children = runs(posted).values()
    assert parent["name"] == "conversation.turn"
    assert [c["run_type"] for c in children] == ["llm", "llm"]
    assert all(c["parent_run_id"] == parent["id"] for c in children)
    assert all(c["trace_id"] == parent["trace_id"] for c in children)


async def test_nothing_is_sent_with_tracing_off():
    client, posted = recording_client()

    with tracing_context(enabled=False, client=client):
        await ollama(reply).create(**REQUEST)
        [e async for e in ollama(streamed_reply).stream(**REQUEST)]

    assert posted == []
