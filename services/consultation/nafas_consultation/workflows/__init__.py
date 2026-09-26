"""The consultation workflows. They decide order and never do I/O."""

from nafas_consultation.workflows.consultation import ConsultationWorkflow

WORKFLOWS = [ConsultationWorkflow]

__all__ = ["WORKFLOWS", "ConsultationWorkflow"]
