"""
The consultation summary: a SOAP note for the doctor and a plain-language
summary for the patient, from one visit's transcript. A forced tool call, so
the shape is fixed; the doctor edits and approves it before anything is filed.
"""

PROMPT_VERSION = "soap-v1"

SYSTEM = """\
You draft the clinical note of one in-person visit from its transcript, for the treating doctor to review.

The transcript is automatic speech recognition of the whole room, in Arabic (any dialect), English or a mix, with times from
the start of the visit. It does not say who is speaking: tell the doctor from the patient by what is said (questions,
examination findings and advice are usually the doctor's; symptoms and history the patient's). It has recognition errors;
read through them, and never invent what is not there.

Write the note in English, the language of the record, keeping drug names, doses and numbers exactly as said.
- subjective: what the patient reports: complaint, history of it, relevant background.
- objective: what was examined or measured in the visit, and results mentioned. Empty if none.
- assessment: the doctor's impression as the doctor said it. Do not add a diagnosis the doctor did not make.
- plan: tests, treatment, advice and follow-up the doctor gave.
- diagnoses, medications, allergies: only those actually discussed. A medication's change is what the doctor decided in
  this visit: started, stopped, changed (dose or frequency), or continued.
- patient_summary: for the patient, in {patient_language}, in plain words a person without medical training understands:
  what was found, what to do, what to watch for, when to come back. Second person, short. No new advice.
- uncertain: anything you could not be sure of, for the doctor to check: an unclear word, a dose you may have misheard,
  a statement you could not attribute to doctor or patient. Empty if nothing.

If the transcript is too short or unclear to write a note from, say so in uncertain and leave the sections empty."""

LANGUAGES = {"ar": "Arabic (simple Modern Standard Arabic)", "en": "English"}

_TEXT = {"type": "string"}

TOOL = {
    "name": "record_consultation_note",
    "description": "Record the draft note of this visit for the doctor to review.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subjective": _TEXT,
            "objective": _TEXT,
            "assessment": _TEXT,
            "plan": _TEXT,
            "diagnoses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": _TEXT, "status": {"type": "string", "enum": ["new", "known", "suspected"]}},
                    "required": ["name", "status"],
                },
            },
            "medications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": _TEXT,
                        "dose": _TEXT,
                        "frequency": _TEXT,
                        "change": {"type": "string", "enum": ["started", "stopped", "changed", "continued"]},
                    },
                    "required": ["name", "change"],
                },
            },
            "allergies": {
                "type": "array",
                "items": {"type": "object", "properties": {"substance": _TEXT, "reaction": _TEXT}, "required": ["substance"]},
            },
            "patient_summary": _TEXT,
            "uncertain": {"type": "array", "items": _TEXT},
        },
        "required": [
            "subjective",
            "objective",
            "assessment",
            "plan",
            "diagnoses",
            "medications",
            "allergies",
            "patient_summary",
            "uncertain",
        ],
    },
}


def system(patient_language: str) -> str:
    return SYSTEM.format(patient_language=LANGUAGES.get(patient_language, LANGUAGES["ar"]))
