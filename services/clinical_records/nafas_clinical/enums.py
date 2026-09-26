from enum import StrEnum


class Visibility(StrEnum):
    """Who may read a record: the doctor alone, or the patient too (and so the patient's assistant)."""

    DOCTOR_ONLY = "doctor_only"
    PATIENT_VISIBLE = "patient_visible"


class HistoryKind(StrEnum):
    VISIT_SUMMARY = "visit_summary"
    # what was said in a recorded visit, timed, as the doctor approved it into the record
    VISIT_TRANSCRIPT = "visit_transcript"
    DIAGNOSIS = "diagnosis"
    MEDICATION = "medication"
    ALLERGY = "allergy"
    LAB_RESULT = "lab_result"
    PROCEDURE = "procedure"
    NOTE = "note"
    INTAKE = "intake"


class DocumentKind(StrEnum):
    REPORT = "report"
    XRAY = "xray"
    CT = "ct"
    MRI = "mri"
    ULTRASOUND = "ultrasound"
    LAB = "lab"
    PRESCRIPTION = "prescription"
    OTHER = "other"


class DocumentStatus(StrEnum):
    # the row exists and an upload link was handed out; the file may not be there yet
    AWAITING_UPLOAD = "awaiting_upload"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class SourceType(StrEnum):
    HISTORY = "history"
    DOCUMENT = "document"
    CONSULTATION = "consultation"
