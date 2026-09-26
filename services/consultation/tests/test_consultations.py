"""A recorded visit end to end: consent, parts, the workflow on Temporal with the real activities, review, filing."""

import uuid

import pytest
from temporalio.testing import ActivityEnvironment
from temporalio.worker import Worker

from nafas_consultation.activities import ConsultationActivities
from nafas_consultation.events import TemporalConsultationEvents, set_events
from nafas_consultation.prompts import soap
from nafas_consultation.schemas import ConsultationRef, consultation_workflow_id
from nafas_consultation.workflows import WORKFLOWS
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.stt.base import Segment, Transcript
from nafas_core.interfaces.stt.fake import FakeSTT

DRAFT = {
    "subjective": "Palpitations for two weeks.",
    "objective": "BP 150/95.",
    "assessment": "Hypertension, not controlled.",
    "plan": "Start amlodipine 5 mg daily; review in two weeks.",
    "diagnoses": [{"name": "Hypertension", "status": "known"}],
    "medications": [{"name": "Amlodipine", "dose": "5 mg", "frequency": "daily", "change": "started"}],
    "allergies": [],
    "patient_summary": "ضغطك عالي، هتبدأ أملوديبين ٥ مجم كل يوم وترجع بعد أسبوعين.",
    "uncertain": ["whether the patient takes anything at night"],
}
HEARD = Transcript("", "ar", [Segment(1.0, 6.0, "عندي خفقان من أسبوعين"), Segment(7.0, 12.0, "الضغط ١٥٠ على ٩٥")])


async def record(api, clinic, parts: int = 2) -> str:
    """What the recorder does: consent, one link per part, PUT each, then finish."""
    started = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/consultations",
        json={"evidence": "verbal, in the room"},
    )
    assert started.status_code == 201, started.text
    cid = started.json()["consultation_id"]
    for index in range(parts):
        link = await api.post(
            f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/parts",
            json={"index": index, "mime": "audio/webm;codecs=opus", "offset_seconds": 60.0 * index, "size_bytes": 4},
        )
        assert link.status_code == 201, link.text
        key = link.json()["upload_url"].removeprefix("memory://put/").split("?")[0]
        await api.storage.put(key, f"part{index}".encode(), "audio/webm")
    return cid


def activities(api, llm, stt=None):
    return ConsultationActivities(api.storage, stt or FakeSTT(HEARD), llm, api.identity, api.clinical, "summary-model")


async def wait_for(api, clinic, cid, status):
    import asyncio

    for _ in range(100):
        body = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
        if body["status"] == status:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError(f"still {body['status']}, not {status}")


async def test_a_visit_is_transcribed_drafted_approved_with_edits_and_filed(api, clinic, temporal, task_queue):
    set_events(TemporalConsultationEvents(temporal, task_queue))
    llm = FakeLLM([tool_use_message(soap.TOOL["name"], DRAFT)])
    stt = FakeSTT(HEARD)
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities(api, llm, stt).all()):
        cid = await record(api, clinic)
        finished = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/finish")
        assert finished.json()["status"] == "transcribing"

        draft = await wait_for(api, clinic, cid, "draft_ready")
        # both parts, the second a minute into the visit
        assert [s["start"] for s in draft["transcript"]] == [1.0, 7.0, 61.0, 67.0]
        assert draft["draft"]["uncertain"] == DRAFT["uncertain"]
        assert (draft["model"], draft["prompt_version"]) == ("summary-model", soap.PROMPT_VERSION)
        [request] = llm.requests
        assert "[01:01] عندي خفقان" in request["messages"][0]["content"]
        assert request["tool_choice"]["name"] == soap.TOOL["name"]
        assert [c["mime_type"] for c in stt.calls] == ["audio/webm", "audio/webm"]
        # waiting for the doctor: in the review list, not yet in the record
        waiting = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations")).json()
        assert [c["consultation_id"] for c in waiting] == [cid]
        assert await api.clinical.history(clinic.doctor_id, clinic.patient_id) == []

        edited = DRAFT | {"plan": "Start amlodipine 5 mg daily; home BP diary; review in two weeks."}
        approved = await api.post(
            f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/approve",
            json={"note": edited, "share_with_patient": True},
        )
        assert approved.json()["status"] == "filing"
        assert await temporal.get_workflow_handle(consultation_workflow_id(cid)).result() == "approved"

    done = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
    assert done["status"] == "approved" and done["approved_at"]
    history = await api.clinical.history(clinic.doctor_id, clinic.patient_id)
    assert sorted(e["kind"] for e in history) == ["diagnosis", "medication", "visit_summary", "visit_summary"]
    assert all(e["source_type"] == "consultation" and e["source_id"] == cid for e in history)
    soap_entry = next(e for e in history if e["kind"] == "visit_summary" and e["visibility"] == "doctor_only")
    assert "home BP diary" in soap_entry["content"]
    # the patient sees the summary their doctor shared, and nothing else of the visit
    mine = await api.clinical.patient_history(clinic.patient_id)
    assert [e["content"] for e in mine] == [DRAFT["patient_summary"]]
    # consent to record was taken for this recording
    kinds = [c["kind"] for c in await api.identity.consents(clinic.patient_id)]
    assert kinds.count("session_recording") == 1


async def test_filing_again_after_a_retry_adds_nothing(api, clinic):
    cid = await record(api, clinic, parts=1)
    acts = activities(api, FakeLLM([tool_use_message(soap.TOOL["name"], DRAFT)]))
    ref = ConsultationRef(cid, str(clinic.doctor_id))
    await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/finish")
    await ActivityEnvironment().run(acts.transcribe, ref)
    await acts.draft(ref)
    await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/approve", json={"note": DRAFT, "share_with_patient": False}
    )

    assert await acts.file(ref) == await acts.file(ref) == 3
    assert len(await api.clinical.history(clinic.doctor_id, clinic.patient_id)) == 3
    assert await api.clinical.patient_history(clinic.patient_id) == []


async def test_a_discarded_draft_leaves_no_audio_and_no_words(api, clinic, temporal, task_queue):
    set_events(TemporalConsultationEvents(temporal, task_queue))
    llm = FakeLLM([tool_use_message(soap.TOOL["name"], DRAFT)])
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities(api, llm).all()):
        cid = await record(api, clinic)
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/finish")
        await wait_for(api, clinic, cid, "draft_ready")
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/discard")
        assert await temporal.get_workflow_handle(consultation_workflow_id(cid)).result() == "discarded"

    gone = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
    assert (gone["status"], gone["transcript"], gone["draft"]) == ("discarded", None, None)
    assert api.storage.objects == {}
    assert await api.clinical.history(clinic.doctor_id, clinic.patient_id) == []


async def test_silence_fails_with_the_reason_and_can_then_be_thrown_away(api, clinic, temporal, task_queue):
    set_events(TemporalConsultationEvents(temporal, task_queue))
    llm = FakeLLM([])
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities(api, llm, FakeSTT("")).all()):
        cid = await record(api, clinic, parts=1)
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/finish")
        assert await temporal.get_workflow_handle(consultation_workflow_id(cid)).result() == "failed"

    failed = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}")).json()
    assert failed["status"] == "failed" and "nothing could be heard" in failed["error"]
    assert llm.requests == []
    discarded = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/discard")
    assert discarded.json()["status"] == "discarded" and api.storage.objects == {}


async def test_only_the_patients_doctor_records_and_each_step_in_its_turn(api, clinic, consultation_events):
    stranger = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.other_patient_id}/consultations",
        json={"evidence": "verbal"},
    )
    assert stranger.status_code == 409 and stranger.json()["reason"] == "not_under_care"

    started = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/consultations", json={"evidence": "verbal"}
    )
    cid = started.json()["consultation_id"]
    base = f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}"

    assert (await api.post(f"{base}/finish")).status_code == 409  # nothing recorded
    link = await api.post(f"{base}/parts", json={"index": 0, "mime": "audio/webm", "offset_seconds": 0, "size_bytes": 3})
    assert (await api.post(f"{base}/finish")).status_code == 409  # not uploaded yet
    wrong_type = await api.post(f"{base}/parts", json={"index": 1, "mime": "video/mp4", "offset_seconds": 60, "size_bytes": 3})
    assert wrong_type.status_code == 422
    too_early = await api.post(f"{base}/approve", json={"note": DRAFT})
    assert too_early.status_code == 409 and too_early.json()["reason"] == "wrong_state"
    # another doctor cannot see it at all
    theirs = await api.get(f"/internal/v1/doctors/{clinic.other_doctor_id}/consultations/{cid}")
    assert theirs.status_code == 404

    key = link.json()["upload_url"].removeprefix("memory://put/").split("?")[0]
    await api.storage.put(key, b"abc", "audio/webm")
    assert (await api.post(f"{base}/finish")).json()["status"] == "transcribing"
    assert consultation_events.events == [("finished", cid)]
    # once it is processing, a new part is refused
    late = await api.post(f"{base}/parts", json={"index": 1, "mime": "audio/webm", "offset_seconds": 60, "size_bytes": 3})
    assert late.status_code == 409


@pytest.mark.parametrize("empty", [{}, {"patient_summary": "only this"}])
async def test_an_empty_note_cannot_be_approved(api, clinic, empty):
    cid = str(uuid.uuid4())
    response = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/consultations/{cid}/approve", json={"note": empty})
    assert response.status_code == 422
