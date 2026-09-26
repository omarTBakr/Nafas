"""Patients' general answers grounded in trusted medical sites: what leaves the clinic, what comes back, what cannot."""

import uuid

from nafas_conversation.logic.context import AppointmentsContext, WebGroundedContext, general_query
from nafas_conversation.logic.turn import answer_turn
from nafas_conversation.prompts import web as web_prompt
from nafas_core.interfaces.llm.fake import FakeLLM, text_message, tool_use_message
from nafas_core.interfaces.search.base import WebResult
from nafas_core.interfaces.search.fake import FakeWebSearch

from .test_medical import MODELS, NOW, Clinic, classified, guarded, scoped, sensitivity

DOMAINS = ["nhs.uk", "medlineplus.gov"]
NHS = WebResult("High blood pressure - NHS", "https://www.nhs.uk/conditions/high-blood-pressure/", "Below 120/80 is ideal.")


def rewrite(query):
    return tool_use_message(web_prompt.TOOL["name"], {"query": query})


async def ask(llm, web, text):
    doctor_id = uuid.uuid4()
    clinic = Clinic(doctor_id)
    context = WebGroundedContext(AppointmentsContext(clinic), web, llm, "classifier-model", DOMAINS)
    return await answer_turn(
        llm,
        clinic,
        clinic,
        patient_id=uuid.uuid4(),
        doctor_id=doctor_id,
        history=[{"role": "user", "content": text}],
        models=MODELS,
        now=NOW,
        context=context,
    )


async def test_the_search_carries_a_general_rewrite_never_the_patients_words():
    web = FakeWebSearch([NHS])
    llm = FakeLLM(
        [
            classified("medical"),
            scoped("in_scope"),
            sensitivity(False),
            rewrite("normal blood pressure range in adults"),
            text_message("حسب هيئة الصحة البريطانية، الضغط الأقل من ١٢٠ على ٨٠ مثالي."),
            guarded("pass"),
        ]
    )

    turn = await ask(llm, web, "أنا منى علي عندي ٥٢ سنة، الضغط الطبيعي كام؟")

    assert web.queries == [("normal blood pressure range in adults", DOMAINS)]
    assert "منى" not in web.queries[0][0]
    rewrite_request = llm.requests[3]
    assert rewrite_request["model"] == "classifier-model" and rewrite_request["tool_choice"]["name"] == "web_query"
    answer_request = llm.requests[4]
    assert (
        "General information from High blood pressure - NHS (https://www.nhs.uk/conditions/high-blood-pressure/)"
        in answer_request["system"]
    )
    # the guard still reads the answer, as for any other
    assert turn.safety["guard"] == "pass" and turn.escalation is None


async def test_no_general_question_no_search_and_a_failed_search_still_answers():
    for script_query, web in ((None, FakeWebSearch([NHS])), ("normal blood pressure", FakeWebSearch(fails=True))):
        llm = FakeLLM(
            [
                classified("medical"),
                scoped("in_scope"),
                sensitivity(False),
                rewrite(script_query),
                text_message("عام."),
                guarded("pass"),
            ]
        )

        turn = await ask(llm, web, "الضغط الطبيعي كام؟")

        assert turn.reply.text == "عام." and "General information" not in llm.requests[4]["system"]
    assert web.queries == [("normal blood pressure", DOMAINS)]


async def test_a_question_the_gates_send_to_the_doctor_is_never_searched():
    web = FakeWebSearch([NHS])
    llm = FakeLLM([classified("medical"), scoped("in_scope"), sensitivity(True, "diagnosis")])

    turn = await ask(llm, web, "الخفقان اللي عندي معناه إيه؟")

    assert turn.escalation is not None and web.queries == []


async def test_a_rewrite_that_is_too_long_or_fails_is_no_query():
    class Down(FakeLLM):
        async def create(self, **params):
            from nafas_core.exceptions.providers import LLMError

            raise LLMError("down")

    long = " ".join(["word"] * 30)
    assert await general_query(FakeLLM([rewrite(long)]), "m", "q") is None
    assert await general_query(Down(), "m", "q") is None
    assert await general_query(FakeLLM([rewrite("  statin side effects  ")]), "m", "q") == "statin side effects"
