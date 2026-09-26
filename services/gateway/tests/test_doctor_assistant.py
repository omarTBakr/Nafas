"""The doctor's assistant through the gateway: a streamed answer that reads the selected patient's record with a tool."""

import json

import pytest

from nafas_core.interfaces.embeddings.factory import set_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_core.interfaces.llm.factory import set_llm
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
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
