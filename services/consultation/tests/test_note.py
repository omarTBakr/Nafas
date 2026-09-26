"""The transcript in visit time, and what an approved note files: framework-free."""

import uuid

from nafas_consultation.logic import transcript
from nafas_consultation.logic.consultations import base_mime
from nafas_consultation.logic.note import Allergy, Diagnosis, Medication, Note, entries
from nafas_core.interfaces.stt.base import Segment, Transcript

NOTE = Note(
    subjective="Palpitations for two weeks, worse at night.",
    objective="BP 150/95, pulse 96 regular.",
    assessment="Uncontrolled hypertension.",
    plan="Start amlodipine, home BP diary, review in two weeks.",
    diagnoses=[Diagnosis(name="Hypertension", status="known")],
    medications=[Medication(name="Amlodipine", dose="5 mg", frequency="once daily", change="started")],
    allergies=[Allergy(substance="Penicillin", reaction="rash")],
    patient_summary="ضغطك عالي. هتبدأ دوا أملوديبين ٥ مجم مرة في اليوم.",
    uncertain=["dose of the night-time tablet"],
)


def test_each_part_is_placed_at_its_offset_in_the_visit():
    first = Transcript("", segments=[Segment(0.0, 4.5, " عندي خفقان "), Segment(5.0, 9.0, "")])
    second = Transcript("Blood pressure is 150 over 95")

    placed = transcript.place(first, 0.0, 60.0) + transcript.place(second, 60.0)

    assert placed == [
        {"start": 0.0, "end": 4.5, "text": "عندي خفقان"},
        {"start": 60.0, "end": 120.0, "text": "Blood pressure is 150 over 95"},
    ]
    assert transcript.for_prompt(placed) == "[00:00] عندي خفقان\n[01:00] Blood pressure is 150 over 95"
    assert transcript.place(Transcript("  "), 120.0) == []


def test_an_approved_note_becomes_doctor_only_entries_and_a_shared_summary():
    cid = uuid.uuid4()

    filed = entries(cid, NOTE, share_with_patient=True)

    assert [(e["kind"], e["visibility"]) for e in filed] == [
        ("visit_summary", "doctor_only"),
        ("diagnosis", "doctor_only"),
        ("medication", "doctor_only"),
        ("allergy", "doctor_only"),
        ("visit_summary", "patient_visible"),
    ]
    assert filed[0]["content"].startswith("Subjective: Palpitations") and "Plan: Start amlodipine" in filed[0]["content"]
    assert filed[2]["content"] == "Amlodipine 5 mg once daily (started)"
    assert filed[3]["content"] == "Penicillin: rash"
    assert all(e["source_type"] == "consultation" and e["source_id"] == str(cid) for e in filed)
    # the model's doubts are for the doctor, never the record
    assert not any("night-time" in e["content"] for e in filed)


def test_filing_twice_names_the_same_entries_and_not_sharing_keeps_the_summary_back():
    cid = uuid.uuid4()

    assert [e["entry_id"] for e in entries(cid, NOTE, True)] == [e["entry_id"] for e in entries(cid, NOTE, True)]
    assert all(e["visibility"] == "doctor_only" for e in entries(cid, NOTE, False))
    assert Note().is_empty() and not NOTE.is_empty()


def test_recorder_types_lose_their_codec():
    assert base_mime("audio/webm;codecs=opus") == "audio/webm"


def test_an_approved_note_files_its_transcript_for_the_doctor_only():
    cid = uuid.uuid4()
    said = "[00:01] عندي خفقان\n[00:05] الضغط ١٥٠ على ٩٥"

    filed = entries(cid, NOTE, share_with_patient=True, transcript=said)
    [kept] = [e for e in filed if e["kind"] == "visit_transcript"]

    assert kept["content"] == said and kept["visibility"] == "doctor_only" and kept["structured"] == {"truncated": False}
    assert kept["entry_id"] == entries(cid, NOTE, True, said)[-2]["entry_id"]
    # nothing said, nothing filed
    assert all(e["kind"] != "visit_transcript" for e in entries(cid, NOTE, True, "  "))


def test_a_very_long_transcript_is_cut_and_says_so():
    from nafas_consultation.logic.note import MAX_TRANSCRIPT

    [kept] = [e for e in entries(uuid.uuid4(), NOTE, False, "x" * (MAX_TRANSCRIPT + 10)) if e["kind"] == "visit_transcript"]

    assert len(kept["content"]) == MAX_TRANSCRIPT and kept["structured"] == {"truncated": True}
