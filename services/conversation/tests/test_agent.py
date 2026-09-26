import json

from anthropic.types import Message, ToolUseBlock, Usage

from nafas_conversation.logic.agent import MAX_STEPS, run_booking_turn
from nafas_conversation.prompts.booking import PROMPT_VERSION, TOOLS
from nafas_core.clients.base import UpstreamRefusal
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm.fake import FakeLLM, text_message

APOLOGY = "معلش، حصلت مشكلة. جرب تاني."


def tool_turn(*calls: tuple[str, dict]) -> Message:
    """One assistant turn asking for one or more tools, as Claude sends it."""
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[ToolUseBlock(type="tool_use", id=f"toolu_{i}", name=n, input=a) for i, (n, a) in enumerate(calls)],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=100, output_tokens=20),
    )


class FakeCalendar:
    def __init__(self, hold_refusal: dict | None = None):
        self.calls: list[tuple[str, object]] = []
        self.hold_refusal = hold_refusal

    async def interpret_time(self, expression):
        self.calls.append(("interpret_time", expression))
        return {
            "timezone": "Africa/Cairo",
            "candidates": [
                {"start": "2026-09-30T05:40:00+03:00", "bookable": False, "reason": "outside_hours"},
                {"start": "2026-09-30T17:40:00+03:00", "bookable": True, "reason": None},
            ],
            "free_slots": [],
        }

    async def hold(self, start, reason_for_visit):
        self.calls.append(("hold", start))
        if self.hold_refusal:
            raise UpstreamRefusal(409, self.hold_refusal)
        return {"appointment_id": "a1", "start": start, "status": "held"}

    async def confirm(self, appointment_id):
        self.calls.append(("confirm", appointment_id))
        return {"appointment_id": appointment_id, "status": "confirmed"}

    async def cancel(self, appointment_id):
        self.calls.append(("cancel", appointment_id))
        return {"appointment_id": appointment_id, "status": "cancelled"}

    async def my_appointments(self):
        self.calls.append(("my_appointments", None))
        return []


async def turn(llm, calendar, text="عايز أحجز الأربع الساعة ٥ و٤٠"):
    return await run_booking_turn(
        llm,
        calendar,
        model="claude-sonnet-5",
        system="system",
        tool_definitions=TOOLS,
        prompt_version=PROMPT_VERSION,
        history=[{"role": "user", "content": text}],
        apology=APOLOGY,
    )


async def test_the_model_extracts_the_calendar_decides_and_the_reply_carries_the_result():
    llm = FakeLLM(
        [
            tool_turn(("interpret_time", {"day": {"weekday": 2}, "hour": 5, "minute": 40})),
            "الأربعاء الساعة ٥:٤٠ مساءً متاح. أحجزهولك؟",
        ]
    )
    calendar = FakeCalendar()

    reply = await turn(llm, calendar)

    assert reply.text == "الأربعاء الساعة ٥:٤٠ مساءً متاح. أحجزهولك؟"
    assert calendar.calls == [("interpret_time", {"day": {"weekday": 2}, "hour": 5, "minute": 40})]
    # the tool result went back to the model in the same shape it gave the call
    second = llm.requests[1]["messages"]
    tool_result = second[-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_0"
    assert json.loads(tool_result["content"])["candidates"][1]["bookable"] is True
    assert reply.prompt_version == PROMPT_VERSION
    assert reply.tokens_in == 100


async def test_a_hold_becomes_an_action_the_ui_can_show():
    llm = FakeLLM([tool_turn(("hold", {"start": "2026-09-30T17:40:00+03:00"})), "حجزتلك الميعاد، أكد خلال ١٠ دقايق."])

    reply = await turn(llm, FakeCalendar(), text="أيوه احجزه")

    assert reply.actions == [
        {"type": "hold", "appointment": {"appointment_id": "a1", "start": "2026-09-30T17:40:00+03:00", "status": "held"}}
    ]


async def test_a_refusal_reaches_the_model_to_explain_it():
    refusal = {"detail": "another booking took this time first", "reason": "taken"}
    llm = FakeLLM([tool_turn(("hold", {"start": "2026-09-30T17:40:00+03:00"})), "للأسف الميعاد اتحجز. تحب ٦:٠٠؟"])

    reply = await turn(llm, FakeCalendar(hold_refusal=refusal))

    result = llm.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and json.loads(result["content"])["reason"] == "taken"
    assert reply.actions == []
    assert "للأسف" in reply.text


async def test_several_tools_in_one_turn_answer_in_one_message():
    llm = FakeLLM([tool_turn(("my_appointments", {}), ("interpret_time", {"day": {"relative_days": 1}})), "تمام"])

    await turn(llm, FakeCalendar())

    results = llm.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_0", "toolu_1"]


async def test_an_unknown_tool_or_missing_argument_is_told_to_the_model_not_raised():
    llm = FakeLLM([tool_turn(("book_everything", {}), ("hold", {})), "آسف"])

    await turn(llm, FakeCalendar())

    results = llm.requests[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)


async def test_a_model_failure_is_an_apology_to_the_patient():
    class Broken:
        async def create(self, **params):
            raise LLMError("Claude returned 400")

    reply = await turn(Broken(), FakeCalendar())

    assert reply.text == APOLOGY


async def test_a_loop_that_never_ends_is_cut_off():
    llm = FakeLLM([tool_turn(("my_appointments", {})) for _ in range(MAX_STEPS)])

    reply = await turn(llm, FakeCalendar())

    assert reply.text == APOLOGY
    assert len(llm.requests) == MAX_STEPS


async def test_an_empty_final_answer_is_never_shown_as_blank():
    empty = text_message("")

    reply = await turn(FakeLLM([empty]), FakeCalendar())

    assert reply.text == APOLOGY


def test_every_tool_the_prompt_names_is_defined():
    names = {tool["name"] for tool in TOOLS}

    assert names == {"interpret_time", "hold", "confirm", "cancel", "my_appointments"}
    assert all(tool["input_schema"]["type"] == "object" for tool in TOOLS)
