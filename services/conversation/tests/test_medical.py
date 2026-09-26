"""The medical pipeline, gate by gate, with a scripted model: who may be answered, what goes to the doctor, and why."""

import uuid
from datetime import UTC, datetime

import pytest

from nafas_conversation.enums import EscalationReason, Intent
from nafas_conversation.logic.safety import mentions_medication_change
from nafas_conversation.logic.turn import FIXED, Models, answer_turn
from nafas_conversation.prompts import intent as intent_prompt
from nafas_conversation.prompts import patient_chat, replies
from nafas_conversation.prompts import safety as safety_prompts
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm.fake import FakeLLM, text_message, tool_use_message

from .test_turn import DOCTOR

MODELS = Models(chat="chat-model", classifier="classifier-model")
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
VISIT = {"doctor_id": None, "status": "confirmed", "start": "2026-09-30T14:40:00+00:00"}
SCOPE = {
    "code": "cardiology",
    "name_en": "Cardiology",
    "name_ar": "قلب",
    "scope_description": "Heart and blood vessels.",
    "in_scope_topics": ["blood pressure"],
    "always_escalate": ["chest pain at rest"],
}


def classified(intent):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


def scoped(verdict):
    return tool_use_message(safety_prompts.SCOPE_TOOL["name"], {"verdict": verdict})


def sensitivity(sensitive, category="general"):
    return tool_use_message(safety_prompts.SENSITIVITY_TOOL["name"], {"sensitive": sensitive, "category": category})


def guarded(verdict):
    return tool_use_message(safety_prompts.GUARD_TOOL["name"], {"verdict": verdict})


class Clinic:
    """Identity and scheduling for one doctor and patient: under care with a confirmed visit unless told otherwise."""

    def __init__(self, doctor_id, under_care=True, visits=True, language="ar"):
        self.doctor_id = doctor_id
        self._under_care, self._visits, self._language = under_care, visits, language

    async def profile(self, patient_id):
        return {"preferred_language": self._language, "dialect": "eg"}

    async def doctor(self, doctor_id):
        return DOCTOR

    async def doctor_scope(self, doctor_id):
        return SCOPE

    async def under_care(self, patient_id, doctor_id):
        return self._under_care

    async def patient_appointments(self, patient_id):
        return [VISIT | {"doctor_id": str(self.doctor_id)}] if self._visits else []

    async def booking_info(self, doctor_id):
        return {"timezone": "Africa/Cairo"}


class Failing(FakeLLM):
    """Fails on the n-th call, answers from the script otherwise."""

    def __init__(self, responses, fail_at):
        super().__init__(responses)
        self.fail_at = fail_at

    async def create(self, **params):
        if len(self.requests) + 1 == self.fail_at:
            self.requests.append(params)
            raise LLMError("down")
        return await super().create(**params)


async def ask(llm, text, **clinic):
    doctor_id = uuid.uuid4()
    directory = Clinic(doctor_id, **clinic)
    return await answer_turn(
        llm,
        directory,
        directory,
        patient_id=uuid.uuid4(),
        doctor_id=doctor_id,
        history=[{"role": "user", "content": text}],
        models=MODELS,
        now=NOW,
    )


async def test_a_general_question_in_scope_is_answered_with_what_the_patient_may_see():
    llm = FakeLLM(
        [
            classified("medical"),
            scoped("in_scope"),
            sensitivity(False),
            text_message("الضغط الطبيعي حوالي ١٢٠ على ٨٠. اسأل د. قلب عن ضغطك أنت."),
            guarded("pass"),
        ]
    )

    turn = await ask(llm, "هو الضغط الطبيعي كام؟")

    assert (turn.intent, turn.escalation) == (Intent.MEDICAL, None)
    assert turn.reply.text.startswith("الضغط الطبيعي") and turn.reply.prompt_version == patient_chat.PROMPT_VERSION
    answer = llm.requests[3]
    assert answer["model"] == "chat-model" and "tools" not in answer
    # the patient's own confirmed visit is the context, in clinic time
    assert "Confirmed appointment with this doctor: Wednesday 30 September 2026, 17:40" in answer["system"]
    assert turn.safety == {
        "versions": ["scope-v1", "sensitivity-v1", "guard-v1"],
        "scope": "in_scope",
        "sensitivity": "general",
        "guard": "pass",
    }


@pytest.mark.parametrize("clinic", [{"under_care": False}, {"visits": False}])
async def test_only_a_patient_with_a_visit_with_this_doctor_gets_medical_answers(clinic):
    llm = FakeLLM([classified("medical")])

    turn = await ask(llm, "هو الضغط الطبيعي كام؟", **clinic)

    assert turn.reply.text == replies.NEEDS_VISIT["ar"] and turn.escalation is None
    assert len(llm.requests) == 1


async def test_another_fields_question_goes_to_the_doctor():
    turn = await ask(FakeLLM([classified("medical"), scoped("out_of_scope_medical")]), "عندي حبوب في وشي")

    assert turn.escalation is EscalationReason.OUT_OF_SCOPE_MEDICAL
    assert turn.reply.text == replies.ESCALATED["ar"].format(doctor="د. قلب") and turn.reply.model == FIXED


async def test_a_sensitive_question_goes_to_the_doctor():
    llm = FakeLLM([classified("medical"), scoped("in_scope"), sensitivity(True, "diagnosis")])

    turn = await ask(llm, "هو الخفقان اللي عندي ده معناه إيه؟")

    assert turn.escalation is EscalationReason.SENSITIVE and turn.safety["sensitivity"] == "diagnosis"


@pytest.mark.parametrize(
    "text",
    ["ينفع أزود جرعة الدوا؟", "can I take 50 mg more?", "I want to stop my blood pressure medicine", "بطلت الدوا من يومين"],
)
async def test_a_dose_or_a_change_of_medicine_goes_to_the_doctor_without_asking_a_model(text):
    llm = FakeLLM([classified("medical"), scoped("in_scope")])

    turn = await ask(llm, text)

    assert turn.escalation is EscalationReason.SENSITIVE and turn.safety["sensitivity"] == "medication"
    # the scope gate ran; the sensitivity model never did
    assert len(llm.requests) == 2


async def test_a_draft_the_guard_blocks_never_reaches_the_patient():
    llm = FakeLLM(
        [
            classified("medical"),
            scoped("in_scope"),
            sensitivity(False),
            text_message("ده غالبًا ارتفاع ضغط، ممكن تبدأ علاج."),
            guarded("block"),
        ]
    )

    turn = await ask(llm, "هو الضغط العالي بيعمل صداع؟")

    assert turn.escalation is EscalationReason.OUTPUT_GUARD
    assert "غالبًا" not in turn.reply.text and turn.safety["guard"] == "block"


@pytest.mark.parametrize(("fail_at", "reason"), [(2, "scope"), (3, "sensitivity"), (4, "answer"), (5, "guard")])
async def test_every_gate_fails_closed(fail_at, reason):
    script = [classified("medical"), scoped("in_scope"), sensitivity(False), text_message("general answer"), guarded("pass")]

    turn = await ask(Failing(script, fail_at), "هو الضغط الطبيعي كام؟")

    assert turn.escalation is not None, f"a failing {reason} step let the answer through"
    assert turn.reply.model == FIXED


async def test_a_question_the_scope_gate_calls_non_medical_goes_to_the_booking_assistant():
    llm = FakeLLM([classified("medical"), scoped("non_medical"), "العيادة بتفتح الساعة ٥."])

    turn = await ask(llm, "العيادة بتفتح إمتى؟")

    assert turn.escalation is None and turn.reply.text == "العيادة بتفتح الساعة ٥."
    assert llm.requests[2]["tools"]  # the booking assistant, with its tools


def test_medication_words_are_caught_in_both_languages_and_small_talk_is_not():
    assert mentions_medication_change("ممكن أوقّف الدواء؟")
    assert mentions_medication_change("Should I double my insulin dose?")
    assert not mentions_medication_change("هو الضغط الطبيعي كام؟")
    assert not mentions_medication_change("thanks, see you Wednesday")


async def test_the_answer_may_draw_on_what_the_doctor_shared():
    from nafas_conversation.logic.context import ClinicalContext

    class Records:
        def __init__(self):
            self.asked = []

        async def search(self, patient_id, doctor_id, query, audience, k):
            self.asked.append((query, audience))
            return [{"content": "Target blood pressure below 130/80.", "details": {"kind": "note"}}]

    records = Records()
    doctor_id = uuid.uuid4()
    clinic = Clinic(doctor_id)
    llm = FakeLLM([classified("medical"), scoped("in_scope"), sensitivity(False), text_message("general"), guarded("pass")])

    await answer_turn(
        llm,
        clinic,
        clinic,
        patient_id=uuid.uuid4(),
        doctor_id=doctor_id,
        history=[{"role": "user", "content": "ضغطي المفروض يكون كام؟"}],
        models=MODELS,
        now=NOW,
        context=ClinicalContext(clinic, records),
    )

    # searched as the patient: only what the doctor shared can come back
    assert records.asked == [("ضغطي المفروض يكون كام؟", "patient")]
    assert "From the patient's record (note): Target blood pressure below 130/80." in llm.requests[3]["system"]
