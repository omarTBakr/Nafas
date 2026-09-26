"""The per-patient search: what each scope can find, and that visibility carries through to the passages."""

from nafas_clinical.enums import HistoryKind, SourceType, Visibility
from nafas_clinical.logic import records, search
from nafas_core.db import session_scope
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings

EMBED = FakeEmbeddings()


async def entry(clinic, text: str, visibility: Visibility):
    async with session_scope(doctor_id=clinic.doctor_id) as session:
        added = await records.add_history(
            session,
            doctor_id=clinic.doctor_id,
            patient_id=clinic.patient_id,
            kind=HistoryKind.NOTE,
            content=text,
            visibility=visibility,
        )
        await search.index(
            session,
            EMBED,
            patient_id=clinic.patient_id,
            doctor_id=clinic.doctor_id,
            source_type=SourceType.HISTORY,
            source_id=added.id,
            text=text,
            visibility=visibility,
            details={"kind": "note"},
        )
    return added


async def found(query: str, clinic, **scope) -> list[str]:
    async with session_scope(**scope) as session:
        return [
            p.content
            for p in await search.search(session, EMBED, patient_id=clinic.patient_id, doctor_id=clinic.doctor_id, query=query)
        ]


async def test_the_doctor_finds_everything_the_patient_only_what_was_shared(clinic):
    await entry(clinic, "Started bisoprolol for palpitations.", Visibility.PATIENT_VISIBLE)
    await entry(clinic, "Suspect anxiety component; discuss gently.", Visibility.DOCTOR_ONLY)

    assert set(await found("bisoprolol", clinic, doctor_id=clinic.doctor_id)) == {
        "Started bisoprolol for palpitations.",
        "Suspect anxiety component; discuss gently.",
    }
    assert await found("anxiety", clinic, patient_id=clinic.patient_id) == ["Started bisoprolol for palpitations."]
    assert await found("bisoprolol", clinic, doctor_id=clinic.other_doctor_id) == []
    assert await found("bisoprolol", clinic, patient_id=clinic.other_patient_id) == []
    assert await found("bisoprolol", clinic) == []


async def test_an_exact_word_ranks_its_passage_first(clinic):
    await entry(clinic, "Blood pressure 150 over 95 at the visit.", Visibility.DOCTOR_ONLY)
    await entry(clinic, "Allergic to penicillin since childhood.", Visibility.DOCTOR_ONLY)

    assert (await found("penicillin", clinic, doctor_id=clinic.doctor_id))[0] == "Allergic to penicillin since childhood."


async def test_sharing_and_unsharing_carry_through_to_search(clinic):
    note = await entry(clinic, "Echo in six months.", Visibility.DOCTOR_ONLY)
    assert await found("echo", clinic, patient_id=clinic.patient_id) == []

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        await records.set_visibility(session, SourceType.HISTORY, note.id, Visibility.PATIENT_VISIBLE)
    assert await found("echo", clinic, patient_id=clinic.patient_id) == ["Echo in six months."]

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        await records.set_visibility(session, SourceType.HISTORY, note.id, Visibility.DOCTOR_ONLY)
    assert await found("echo", clinic, patient_id=clinic.patient_id) == []


async def test_another_doctor_cannot_change_what_is_shared(clinic):
    import pytest

    from nafas_clinical.exceptions import RecordNotFoundError

    note = await entry(clinic, "Echo in six months.", Visibility.DOCTOR_ONLY)
    async with session_scope(doctor_id=clinic.other_doctor_id) as session:
        with pytest.raises(RecordNotFoundError):
            await records.set_visibility(session, SourceType.HISTORY, note.id, Visibility.PATIENT_VISIBLE)
