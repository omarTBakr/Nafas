"""Dataclasses crossing a Temporal boundary. New fields need defaults."""

from dataclasses import dataclass

CONSULTATION_WORKFLOW = "ConsultationWorkflow"
APPROVED_SIGNAL = "approved"
DISCARD_SIGNAL = "discard"


def consultation_workflow_id(consultation_id: str) -> str:
    return f"consultation-{consultation_id}"


@dataclass
class ConsultationRef:
    consultation_id: str
    doctor_id: str


@dataclass
class Failure:
    consultation_id: str
    doctor_id: str
    error: str
