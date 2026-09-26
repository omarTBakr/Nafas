"""Voice around a turn: transcription in, the dialect tag, a spoken reply out, end to end on the workflow and database."""

import uuid

from temporalio.worker import Worker

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.client import send_patient_message
from nafas_conversation.enums import Modality
from nafas_conversation.logic import messages, voice
from nafas_conversation.logic.turn import Models
from nafas_conversation.logic.voice import VoiceProviders
from nafas_conversation.prompts import intent as intent_prompt
from nafas_conversation.prompts import replies
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.enums.dialect import Dialect
from nafas_core.interfaces.dialect.fake import FakeDialectClassifier
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.storage.fake import InMemoryStorage
from nafas_core.interfaces.stt.fake import FakeSTT
from nafas_core.interfaces.tts.fake import FakeTTS

from .test_turn import DOCTOR


class Directory:
    def __init__(self, dialect: str | None = "eg", language: str = "ar"):
        self.profile_body = {"preferred_language": language, "dialect": dialect, "voice": "female"}

    async def profile(self, patient_id):
        return self.profile_body

    async def doctor(self, doctor_id):
        return DOCTOR

    async def booking_info(self, doctor_id):
        return {"timezone": "Africa/Cairo"}


class MedicalDirectory(Directory):
    async def under_care(self, patient_id, doctor_id):
        return False


def classified(intent: str):
    return tool_use_message(intent_prompt.TOOL["name"], {"intent": intent})


def providers(transcript: str = "عايز أحجز الأربعاء", **kwargs) -> VoiceProviders:
    storage = InMemoryStorage()
    storage.objects["doctor/d/patient/p/voice/note.webm"] = (b"webm-bytes", "audio/webm")
    return VoiceProviders(
        stt=FakeSTT(transcript), tts=kwargs.get("tts", FakeTTS()), storage=storage, dialects=FakeDialectClassifier()
    )


async def voice_turn(parties, temporal, task_queue, llm, voice_providers, directory=None):
    directory = directory or Directory()
    activities = ConversationActivities(llm, directory, directory, Models("chat", "classifier"), voice_providers)
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        reply = await send_patient_message(
            temporal,
            patient_id=str(parties.patient_id),
            doctor_id=str(parties.doctor_id),
            audio_key="doctor/d/patient/p/voice/note.webm",
            audio_mime="audio/webm",
            task_queue=task_queue,
        )
        await temporal.get_workflow_handle(f"conv-{parties.doctor_id}-{parties.patient_id}").terminate()
    return reply


async def test_a_voice_note_is_transcribed_answered_and_answered_aloud(parties, temporal, task_queue):
    vp = providers()
    llm = FakeLLM([classified("booking"), "تمام، الأربعاء الساعة ٥:٤٠ فاضي."])

    reply = await voice_turn(parties, temporal, task_queue, llm, vp)

    assert reply.patient_text == "عايز أحجز الأربعاء"
    assert vp.stt.calls[0]["audio"] == b"webm-bytes" and vp.stt.calls[0]["language_hint"] == "ar"
    # the model saw the transcript, as if it had been typed
    assert llm.requests[1]["messages"][-1]["content"] == "عايز أحجز الأربعاء"
    # spoken in the patient's dialect and voice, times as words
    assert vp.tts.calls == [{"text": "تمام، الأربعاء الساعة خمسة وأربعين فاضي.", "dialect": "eg", "voice": "female"}]
    assert reply.audio_key == f"doctor/{parties.doctor_id}/patient/{parties.patient_id}/voice/{reply.message_id}.wav"
    assert reply.audio_key in vp.storage.objects

    stored = await messages.patient_thread(parties.patient_id, parties.doctor_id, 10)
    assert [(m.modality, m.audio_key is not None) for m in stored] == [(Modality.VOICE, True), (Modality.VOICE, True)]
    # the transcript was tagged with its dialect for suggestions
    assert stored[0].detected_dialect == "eg"


async def test_medical_answers_are_never_spoken(parties, temporal, task_queue):
    vp = providers("هو الدوا ده ليه آثار جانبية؟")

    reply = await voice_turn(parties, temporal, task_queue, FakeLLM([classified("medical")]), vp, MedicalDirectory())

    # a patient with no visit yet is told to book first, in text only
    assert reply.intent == "medical" and reply.text == replies.NEEDS_VISIT["ar"]
    assert reply.audio_key is None and vp.tts.calls == []


async def test_a_voice_note_that_says_nothing_gets_asked_again(parties, temporal, task_queue):
    vp = providers("")

    reply = await voice_turn(parties, temporal, task_queue, FakeLLM(), vp)

    assert reply.text == replies.NOT_HEARD["ar"]


async def test_no_voice_until_the_patient_chooses_a_dialect_and_none_when_tts_fails(parties):
    reply_id = uuid.uuid4()
    unchosen = await voice.speak_reply(
        providers(),
        Directory(dialect=None),
        doctor_id=parties.doctor_id,
        patient_id=parties.patient_id,
        reply_id=reply_id,
        text="تمام",
    )
    failing = await voice.speak_reply(
        providers(tts=FakeTTS(fail=True)),
        Directory(),
        doctor_id=parties.doctor_id,
        patient_id=parties.patient_id,
        reply_id=reply_id,
        text="تمام",
    )

    assert unchosen is None and failing is None


async def test_a_dialect_is_suggested_only_from_enough_agreeing_confident_readings(parties):
    conversation_id = await messages.open_conversation(parties.patient_id, parties.doctor_id)
    vp = providers()

    async def written(text: str, classifier: FakeDialectClassifier):
        message_id = uuid.uuid4()
        await messages.add_patient_message(parties.patient_id, message_id, conversation_id, text)
        await voice.tag_dialect(VoiceProviders(vp.stt, vp.tts, vp.storage, classifier), parties.patient_id, message_id, text)

    await written("إزيك", FakeDialectClassifier(Dialect.EGYPTIAN))
    await written("عايز أحجز", FakeDialectClassifier(Dialect.EGYPTIAN))
    assert await voice.suggested_dialect(parties.patient_id) is None

    # a low-confidence reading is not stored, so it does not count
    await written("شكرا", FakeDialectClassifier(Dialect.LEBANESE, score=0.3))
    assert await voice.suggested_dialect(parties.patient_id) is None

    await written("بكرة العصر", FakeDialectClassifier(Dialect.EGYPTIAN))
    assert await voice.suggested_dialect(parties.patient_id) == "eg"
    # never another patient's
    assert await voice.suggested_dialect(parties.other_patient_id) is None
