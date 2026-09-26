"""The doctor assistant's loop: it streams, runs the tools the model asks for, and never runs away."""

import json

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm.fake import FakeLLM
from nafas_doctor_assistant.logic.chat import MAX_STEPS, run_doctor_chat


def message(content, stop="end_turn") -> Message:
    return Message(
        id="m",
        type="message",
        role="assistant",
        model="chat-model",
        content=content,
        stop_reason=stop,
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def asks(name="search_patient_docs", arguments=None, tool_id="t1") -> Message:
    return message([ToolUseBlock(type="tool_use", id=tool_id, name=name, input=arguments or {"query": "LDL"})], "tool_use")


class Tools:
    def __init__(self, fails=False):
        self.calls, self._fails = [], fails

    async def run(self, name, arguments):
        self.calls.append((name, arguments))
        if self._fails:
            raise RuntimeError("clinical-records is down")
        return [{"source": "lipid.pdf", "text": "LDL 162"}]


async def run(llm, tools):
    return [
        e
        async for e in run_doctor_chat(
            llm,
            tools,
            model="chat-model",
            system="s",
            tool_definitions=[],
            prompt_version="doctor-chat-v1",
            history=[{"role": "user", "content": "LDL?"}],
        )
    ]


async def test_a_tool_is_run_its_result_goes_back_and_the_answer_streams():
    llm = FakeLLM([asks(), message([TextBlock(type="text", text="Her LDL was 162 mg/dL (lipid.pdf).")])])
    tools = Tools()

    events = await run(llm, tools)

    assert events[0] == {"type": "tool", "name": "search_patient_docs"}
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Her LDL was 162 mg/dL (lipid.pdf)."
    assert events[-1] == {
        "type": "done",
        "model": "chat-model",
        "prompt_version": "doctor-chat-v1",
        "tokens_in": 20,
        "tokens_out": 10,
    }
    assert tools.calls == [("search_patient_docs", {"query": "LDL"})]
    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["tool_use_id"] == "t1" and json.loads(result["content"])[0]["text"] == "LDL 162" and not result["is_error"]


async def test_a_failing_tool_is_reported_to_the_model_not_to_the_doctor_as_a_crash():
    llm = FakeLLM([asks(), message([TextBlock(type="text", text="I could not read the record just now.")])])

    events = await run(llm, Tools(fails=True))

    [result] = llm.requests[1]["messages"][-1]["content"]
    assert result["is_error"] and "could not be read" in result["content"]
    assert events[-1]["type"] == "done"


async def test_the_model_being_down_ends_the_turn_with_an_error_event():
    class Down(FakeLLM):
        async def stream(self, **params):
            raise LLMError("overloaded")
            yield  # an async generator

    events = await run(Down(), Tools())

    assert events == [{"type": "error", "detail": "the assistant is unavailable; try again shortly"}]


async def test_a_model_that_keeps_calling_tools_is_stopped():
    llm = FakeLLM([asks(tool_id=f"t{i}") for i in range(MAX_STEPS)])
    tools = Tools()

    events = await run(llm, tools)

    assert len(tools.calls) == MAX_STEPS
    assert events[-1] == {"type": "error", "detail": "the assistant could not finish; ask a narrower question"}
