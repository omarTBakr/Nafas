"""The conversation service's workflows. They decide order and never do I/O."""

from nafas_conversation.workflows.escalation import EscalationWorkflow
from nafas_conversation.workflows.patient_conversation import PatientConversationWorkflow

WORKFLOWS = [PatientConversationWorkflow, EscalationWorkflow]

__all__ = ["WORKFLOWS", "EscalationWorkflow", "PatientConversationWorkflow"]
