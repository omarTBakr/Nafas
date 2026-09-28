import json

from anthropic.types import Message, ToolUseBlock, Usage

from nafas_conversation.logic.agent import EMPTY_ANSWER_NUDGE, MAX_STEPS, run_booking_turn
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


async def test_an_empty_final_answer_is_asked_for_once_more():
    """Local models sometimes end a turn silently, often right after a tool; one nudge usually brings the words."""
    llm = FakeLLM([text_message(""), "حجزتلك الخميس الساعة ٦. أكد من الزرار."])

    reply = await turn(llm, FakeCalendar())

    assert reply.text == "حجزتلك الخميس الساعة ٦. أكد من الزرار."
    nudge = llm.requests[1]["messages"][-1]
    assert nudge["role"] == "user" and nudge["content"] == EMPTY_ANSWER_NUDGE


async def test_two_empty_answers_are_an_apology_never_a_blank():
    reply = await turn(FakeLLM([text_message(""), text_message("")]), FakeCalendar())

    assert reply.text == APOLOGY


async def test_a_time_the_model_cannot_write_is_told_back_not_raised():
    class Picky(FakeCalendar):
        async def hold(self, start, reason_for_visit):
            raise ValueError(f"Invalid isoformat string: {start!r}")

    llm = FakeLLM([tool_turn(("hold", {"start": "Thursday 6pm"})), "Sorry, which time exactly?"])

    reply = await turn(llm, Picky())

    result = llm.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "invalid argument" in result["content"]
    assert reply.text == "Sorry, which time exactly?"


def test_every_tool_the_prompt_names_is_defined():
    names = {tool["name"] for tool in TOOLS}

    assert names == {"interpret_time", "hold", "confirm", "cancel", "my_appointments"}
    assert all(tool["input_schema"]["type"] == "object" for tool in TOOLS)


class StreamingLLM(FakeLLM):
    """A FakeLLM whose replies can also be streamed, in word-sized pieces."""

    async def stream(self, **params):
        from nafas_core.interfaces.llm.base import StreamEvent

        message = await self.create(**params)
        for block in message.content:
            if block.type == "text":
                for word in block.text.split(" "):
                    yield StreamEvent(text=word + " ")
        yield StreamEvent(message=message)


async def test_with_a_listener_the_reply_arrives_in_pieces_as_it_is_written():
    pieces: list[str] = []

    async def heard(piece: str) -> None:
        pieces.append(piece)

    llm = StreamingLLM([tool_turn(("my_appointments", {})), "You have no appointments yet."])
    reply = await run_booking_turn(
        llm,
        FakeCalendar(),
        model="m",
        system="s",
        tool_definitions=TOOLS,
        prompt_version=PROMPT_VERSION,
        history=[{"role": "user", "content": "my appointments?"}],
        apology=APOLOGY,
        on_text=heard,
    )

    assert reply.text == "You have no appointments yet."
    assert "".join(pieces).strip() == "You have no appointments yet."
    assert len(pieces) == 5
