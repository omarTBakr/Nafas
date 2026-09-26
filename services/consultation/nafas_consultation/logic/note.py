"""
A visit's note: the shape the model drafts, the doctor edits, and filing reads.

Filing turns an approved note into history entries in clinical-records: the
SOAP note as the visit summary, one entry per diagnosis, medication and
allergy, all for the doctor only, and the patient's summary as its own entry
the patient can see when the doctor chose to share it. Each entry's id comes
from the consultation and its place in the note, so filing again after a
retry writes nothing twice.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

MAX_TEXT = 20000


class Diagnosis(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    status: Literal["new", "known", "suspected"] = "new"


class Medication(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    dose: str = Field(default="", max_length=200)
    frequency: str = Field(default="", max_length=200)
    change: Literal["started", "stopped", "changed", "continued"] = "continued"


class Allergy(BaseModel):
    substance: str = Field(min_length=1, max_length=300)
    reaction: str = Field(default="", max_length=300)


class Note(BaseModel):
    subjective: str = Field(default="", max_length=MAX_TEXT)
    objective: str = Field(default="", max_length=MAX_TEXT)
    assessment: str = Field(default="", max_length=MAX_TEXT)
    plan: str = Field(default="", max_length=MAX_TEXT)
    diagnoses: list[Diagnosis] = Field(default_factory=list, max_length=50)
    medications: list[Medication] = Field(default_factory=list, max_length=50)
    allergies: list[Allergy] = Field(default_factory=list, max_length=50)
    patient_summary: str = Field(default="", max_length=MAX_TEXT)
    # the model's doubts, for the doctor; never filed
    uncertain: list[str] = Field(default_factory=list, max_length=50)

    def is_empty(self) -> bool:
        return not any((self.subjective, self.objective, self.assessment, self.plan))


def soap_text(note: Note) -> str:
    parts = [("Subjective", note.subjective), ("Objective", note.objective), ("Assessment", note.assessment), ("Plan", note.plan)]
    return "\n\n".join(f"{title}: {text.strip()}" for title, text in parts if text.strip())


def _medication(m: Medication) -> str:
    detail = " ".join(p for p in (m.dose.strip(), m.frequency.strip()) if p)
    return f"{m.name.strip()}{f' {detail}' if detail else ''} ({m.change})"


def _allergy(a: Allergy) -> str:
    return f"{a.substance.strip()}{f': {a.reaction.strip()}' if a.reaction.strip() else ''}"


def entry_id(consultation_id: uuid.UUID, slot: str) -> uuid.UUID:
    return uuid.uuid5(consultation_id, slot)


def entries(consultation_id: uuid.UUID, note: Note, share_with_patient: bool) -> list[dict]:
    """The history entries an approved note becomes, as clinical-records' NewEntry bodies."""
    source = {"source_type": "consultation", "source_id": str(consultation_id)}
    out = [
        {
            "entry_id": str(entry_id(consultation_id, "visit_summary")),
            "kind": "visit_summary",
            "content": soap_text(note),
            "structured": note.model_dump(include={"subjective", "objective", "assessment", "plan"}),
            "visibility": "doctor_only",
            **source,
        }
    ]
    for i, d in enumerate(note.diagnoses):
        out.append(
            {
                "entry_id": str(entry_id(consultation_id, f"diagnosis-{i}")),
                "kind": "diagnosis",
                "content": f"{d.name.strip()} ({d.status})",
                "structured": d.model_dump(),
                "visibility": "doctor_only",
                **source,
            }
        )
    for i, m in enumerate(note.medications):
        out.append(
            {
                "entry_id": str(entry_id(consultation_id, f"medication-{i}")),
                "kind": "medication",
                "content": _medication(m),
                "structured": m.model_dump(),
                "visibility": "doctor_only",
                **source,
            }
        )
    for i, a in enumerate(note.allergies):
        out.append(
            {
                "entry_id": str(entry_id(consultation_id, f"allergy-{i}")),
                "kind": "allergy",
                "content": _allergy(a),
                "structured": a.model_dump(),
                "visibility": "doctor_only",
                **source,
            }
        )
    if share_with_patient and note.patient_summary.strip():
        out.append(
            {
                "entry_id": str(entry_id(consultation_id, "patient_summary")),
                "kind": "visit_summary",
                "content": note.patient_summary.strip(),
                "structured": {"audience": "patient"},
                "visibility": "patient_visible",
                **source,
            }
        )
    return out
