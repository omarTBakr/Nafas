"""The doctor assistant's tools, over fake services: what each returns, and that none reaches past its doctor and patient."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from nafas_doctor_assistant.logic.tools import DoctorTools

DOCTOR, PATIENT, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
NOW = datetime.now(UTC)


def at(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


class Services:
    """identity, scheduling, clinical and conversation in one: each records what it was asked."""

    def __init__(self, appointments=None, history=None, documents=None, escalations=None, hits=None, today=None):
        self.asked: list[tuple] = []
        self._appointments, self._history, self._documents = appointments or [], history or [], documents or []
        self._escalations, self._hits, self._today = escalations or [], hits or [], today or []

    async def doctor_patient_appointments(self, doctor_id, patient_id):
        self.asked.append(("appointments", doctor_id, patient_id))
        return self._appointments

    async def history(self, doctor_id, patient_id):
        return self._history

    async def documents(self, doctor_id, patient_id):
        return self._documents

    async def escalations(self, doctor_id, statuses, patient_id):
        return self._escalations

    async def search(self, patient_id, doctor_id, query, audience, k):
        self.asked.append(("search", patient_id, doctor_id, query, audience))
        return self._hits

    async def doctor_appointments(self, doctor_id, start, end):
        self.asked.append(("today", doctor_id, start, end))
        return self._today

    async def patient_names(self, doctor_id, patient_ids):
        return {str(p): "منى علي" for p in patient_ids if p == PATIENT}


def tools(services: Services, patient_id=PATIENT, timezone="Africa/Cairo") -> DoctorTools:
    return DoctorTools(
        doctor_id=DOCTOR,
        patient_id=patient_id,
        timezone=timezone,
        identity=services,
        scheduling=services,
        clinical=services,
        conversation=services,
    )


async def test_without_a_selected_patient_the_patient_tools_say_so():
    t = tools(Services(), patient_id=None)

    assert "no patient is selected" in (await t.get_patient_timeline())["error"]
    assert "no patient is selected" in (await t.search_patient_docs("LDL"))["error"]


async def test_the_timeline_is_newest_first_in_clinic_time_with_what_each_item_is():
    services = Services(
        appointments=[{"start": at(-timedelta(days=30)), "status": "completed", "reason_for_visit": "palpitations"}],
        history=[{"occurred_at": at(-timedelta(days=2)), "kind": "note", "content": "BP 150/95", "visibility": "doctor_only"}],
        documents=[
            {
                "created_at": at(-timedelta(days=1)),
                "filename": "echo.jpg",
                "kind": "report",
                "status": "indexed",
                "ai_description": "an echo report",
                "ai_label": "AI description, not a read",
            }
        ],
        escalations=[{"created_at": at(-timedelta(hours=1)), "question": "dose?", "status": "answered", "doctor_reply": "no"}],
    )

    timeline = await tools(services).get_patient_timeline()

    assert [i["type"] for i in timeline] == ["escalation", "document", "history", "appointment"]
    assert {k: v for k, v in timeline[0].items() if k != "when"} == {
        "type": "escalation",
        "question": "dose?",
        "status": "answered",
        "reply": "no",
    }
    assert timeline[1]["ai_description"] == "[AI description, not a read] an echo report"
    assert timeline[2]["shared_with_patient"] is False and timeline[3]["reason_for_visit"] == "palpitations"
    # clinic time, not UTC: Cairo is ahead
    local = (NOW - timedelta(hours=1)).astimezone(ZoneInfo("Africa/Cairo"))
    assert timeline[0]["when"] == local.strftime("%a %d %b %Y %H:%M")
    assert services.asked == [("appointments", DOCTOR, PATIENT)]


async def test_the_timeline_limit_is_kept_between_one_and_a_hundred():
    services = Services(
        history=[
            {"occurred_at": at(-timedelta(minutes=i)), "kind": "note", "content": str(i), "visibility": "doctor_only"}
            for i in range(120)
        ]
    )

    assert len(await tools(services).get_patient_timeline(0)) == 1
    assert len(await tools(services).get_patient_timeline(500)) == 100


async def test_record_search_is_as_this_doctor_and_names_its_source():
    services = Services(
        hits=[
            {"details": {"filename": "lipid.pdf"}, "source_type": "document", "content": "LDL 162"},
            {"details": {"kind": "allergy"}, "source_type": "history", "content": "penicillin"},
            {"details": {}, "source_type": "consultation", "content": "..."},
        ]
    )

    found = await tools(services).search_patient_docs("LDL")

    assert [f["source"] for f in found] == ["lipid.pdf", "allergy", "consultation"]
    assert services.asked == [("search", PATIENT, DOCTOR, "LDL", "doctor")]


async def test_today_is_the_clinic_day_and_a_held_slot_has_no_name_yet():
    services = Services(
        today=[
            {"start": at(timedelta(hours=1)), "status": "confirmed", "patient_id": str(PATIENT)},
            {"start": at(timedelta(hours=2)), "status": "held", "patient_id": str(OTHER)},
        ]
    )

    schedule = await tools(services).get_today_schedule()

    assert [s["patient"] for s in schedule] == ["منى علي", "held, not yet confirmed"]
    _, _, start, end = services.asked[0]
    assert end - start == timedelta(days=1) and start.utcoffset() is not None


async def test_the_next_patient_is_the_earliest_confirmed_one_still_due():
    services = Services(
        today=[
            {"start": at(-timedelta(minutes=45)), "status": "confirmed", "patient_id": str(OTHER)},  # long past
            {"start": at(timedelta(hours=2)), "status": "confirmed", "patient_id": str(OTHER)},
            {"start": at(-timedelta(minutes=10)), "status": "confirmed", "patient_id": str(PATIENT)},  # late, still due
            {"start": at(timedelta(minutes=5)), "status": "held", "patient_id": str(OTHER)},
        ]
    )

    nxt = (await tools(services).get_next_patient())["next"]

    assert nxt["patient_id"] == str(PATIENT) and nxt["patient"] == "منى علي"
    assert await tools(Services()).get_next_patient() == {"next": None}


async def test_the_model_can_only_call_the_tools_that_exist():
    t = tools(Services(hits=[]))

    assert await t.run("search_patient_docs", {"query": "x"}) == []
    assert await t.run("delete_patient", {}) == {"error": "no tool named delete_patient"}
    assert await t.run("get_next_patient", {}) == {"next": None}


async def test_web_search_is_offered_only_when_on_and_its_sources_come_back_cited():
    from nafas_core.interfaces.search.base import WebResult
    from nafas_core.interfaces.search.fake import FakeWebSearch
    from nafas_doctor_assistant.prompts import doctor_chat

    web = FakeWebSearch([WebResult("ESC 2024 hypertension guideline", "https://escardio.org/htn", "Target below 130/80.")])
    t = DoctorTools(
        doctor_id=DOCTOR,
        patient_id=PATIENT,
        timezone="UTC",
        identity=None,
        scheduling=None,
        clinical=None,
        conversation=None,
        web=web,
    )

    found = await t.run("search_web", {"query": "hypertension target in adults under 65"})

    assert found == [
        {"title": "ESC 2024 hypertension guideline", "url": "https://escardio.org/htn", "text": "Target below 130/80."}
    ]
    assert web.queries == [("hypertension target in adults under 65", None)]
    assert "search_web" in [tool["name"] for tool in doctor_chat.tools(True)]
    assert "search_web" not in [tool["name"] for tool in doctor_chat.tools(False)]
    assert "never put a patient's name" in doctor_chat.WEB


async def test_without_web_search_or_when_it_fails_the_model_is_told_not_crashed():
    from nafas_core.interfaces.search.fake import FakeWebSearch

    off = tools(Services())
    down = DoctorTools(
        doctor_id=DOCTOR,
        patient_id=PATIENT,
        timezone="UTC",
        identity=None,
        scheduling=None,
        clinical=None,
        conversation=None,
        web=FakeWebSearch(fails=True),
    )

    assert await off.run("search_web", {"query": "x"}) == {"error": "web search is not available here"}
    assert "failed just now" in (await down.run("search_web", {"query": "x"}))["error"]
