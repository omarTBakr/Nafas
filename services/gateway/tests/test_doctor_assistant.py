"""The doctor's assistant through the gateway: a streamed answer that reads the selected patient's record with a tool."""

import json

import pytest

from nafas_core.interfaces.embeddings.factory import set_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_core.interfaces.llm.factory import set_llm
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.stt.factory import set_stt
from nafas_core.interfaces.stt.fake import FakeSTT
from nafas_core.interfaces.tts import set_tts
from nafas_core.interfaces.tts.fake import FakeTTS
from nafas_doctor_assistant.prompts import doctor_chat

from .conftest import DOCTOR_PASSWORD, browser, sign_up
from .test_records_flow import booked


def events(body: str) -> list[dict]:
    return [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]


@pytest.fixture
def scripted():
    def use(script):
        llm = FakeLLM(script)
        set_llm(llm)
        return llm

    set_embeddings(FakeEmbeddings())
    yield use
    set_llm(None)
    set_embeddings(None)


async def test_an_answer_streams_after_reading_the_patients_record(doctor_id, scripted):
    llm = scripted(
        [tool_use_message("get_patient_timeline", {}), "She was started on bisoprolol for palpitations (note, today)."]
    )
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        patient_id = await booked(sara, doctor_id)
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        await doctor.post(f"/api/doctor/patients/{patient_id}/history", json={"content": "Started bisoprolol for palpitations."})

        answer = await doctor.post(
            "/api/doctor/assistant",
            json={"patient_id": patient_id, "messages": [{"role": "user", "content": "What is she on?"}]},
        )

    streamed = events(answer.text)
    assert answer.headers["content-type"].startswith("text/event-stream")
    assert streamed[0] == {"type": "tool", "name": "get_patient_timeline"}
    assert (
        "".join(e["text"] for e in streamed if e["type"] == "text")
        == "She was started on bisoprolol for palpitations (note, today)."
    )
    assert streamed[-1]["type"] == "done" and streamed[-1]["prompt_version"] == doctor_chat.PROMPT_VERSION

    # the model was told who is selected, and the tool read that patient's record
    first, second = llm.requests
    assert patient_id in first["system"] and "سارة" in first["system"]
    [result] = second["messages"][-1]["content"]
    assert "Started bisoprolol for palpitations." in result["content"] and result["is_error"] is False


async def test_a_patient_not_under_care_cannot_be_selected(doctor_id, scripted):
    scripted([])
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        patient_id = (await sara.get("/api/auth/me")).json()["patient_id"]
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        refused = await doctor.post(
            "/api/doctor/assistant", json={"patient_id": patient_id, "messages": [{"role": "user", "content": "hi"}]}
        )
        by_patient = await sara.post("/api/doctor/assistant", json={"messages": [{"role": "user", "content": "hi"}]})

    assert refused.status_code == 403
    assert by_patient.status_code == 403


async def test_without_a_patient_the_patient_tools_say_so(doctor_id, scripted):
    llm = scripted([tool_use_message("search_patient_docs", {"query": "echo"}), "Open a patient first."])
    async with browser() as doctor:
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        answer = await doctor.post("/api/doctor/assistant", json={"messages": [{"role": "user", "content": "Any echo reports?"}]})

    assert events(answer.text)[-1]["type"] == "done"
    [result] = llm.requests[1]["messages"][-1]["content"]
    assert "no patient is selected" in result["content"]


@pytest.fixture
def voice():
    def use(fail: bool = False) -> FakeTTS:
        tts = FakeTTS(fail=fail)
        set_tts(tts)
        return tts

    yield use
    set_tts(None)


async def test_the_doctor_hears_a_passage_in_the_dialect_chosen(doctor_id, voice):
    tts = voice()
    passage = "بدأت بيسوبرولول ٢.٥ مجم للخفقان."
    async with browser() as doctor, browser() as sara:
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        spoken = await doctor.post("/api/doctor/speak", json={"text": passage, "dialect": "sa", "voice": "male"})
        default = await doctor.post("/api/doctor/speak", json={"text": passage})
        too_long = await doctor.post("/api/doctor/speak", json={"text": "ا" * 601})
        await sign_up(sara)
        by_patient = await sara.post("/api/doctor/speak", json={"text": passage})

    assert spoken.status_code == 200 and spoken.headers["content-type"] == "audio/wav"
    assert spoken.content == b"RIFF-fake-wav"
    # a doctor's passage is read as written: doses and medicines are not held back, as they are for a patient
    assert tts.calls[0] == {"text": passage, "dialect": "sa", "voice": "male"}
    assert default.status_code == 200 and tts.calls[1]["dialect"] == "eg"
    assert too_long.status_code == 422
    assert by_patient.status_code == 403
    assert len(tts.calls) == 2


async def test_an_unavailable_voice_is_a_refusal_the_browser_falls_back_from(doctor_id, voice):
    voice(fail=True)
    async with browser() as doctor:
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        refused = await doctor.post("/api/doctor/speak", json={"text": "مرحبا"})

    assert refused.status_code == 503 and refused.json()["reason"] == "voice_unavailable"


class BrokenSTT:
    async def transcribe(self, audio, mime_type, language_hint=None, diarize=False):
        from nafas_core.exceptions.providers import STTError

        raise STTError("down")


async def test_a_dictated_question_comes_back_as_text_and_is_not_kept(doctor_id, storage):
    stt = FakeSTT("  ما آخر نتيجة تحليل دهون للمريضة؟  ")
    set_stt(stt)
    try:
        async with browser() as doctor, browser() as sara:
            await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
            heard = await doctor.post(
                "/api/doctor/transcribe",
                files={"audio": ("q.webm", b"webm-bytes", "audio/webm;codecs=opus")},
                data={"language": "ar"},
            )
            wrong_type = await doctor.post("/api/doctor/transcribe", files={"audio": ("q.txt", b"x", "text/plain")})
            empty = await doctor.post("/api/doctor/transcribe", files={"audio": ("q.webm", b"", "audio/webm")})
            await sign_up(sara)
            by_patient = await sara.post("/api/doctor/transcribe", files={"audio": ("q.webm", b"webm-bytes", "audio/webm")})
            set_stt(BrokenSTT())
            down = await doctor.post("/api/doctor/transcribe", files={"audio": ("q.webm", b"webm-bytes", "audio/webm")})
    finally:
        set_stt(None)

    assert heard.status_code == 200 and heard.json() == {"text": "ما آخر نتيجة تحليل دهون للمريضة؟", "language": "ar"}
    assert stt.calls == [{"audio": b"webm-bytes", "mime_type": "audio/webm", "language_hint": "ar", "diarize": False}]
    # nothing was put in storage: a dictation is not a record
    assert storage.objects == {}
    assert wrong_type.status_code == 415 and empty.status_code == 422
    assert by_patient.status_code == 403
    assert down.status_code == 503 and down.json()["reason"] == "stt_unavailable"
