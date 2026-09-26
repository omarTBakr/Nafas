"""The conversation service's workflows. They decide order and never do I/O."""

from nafas_conversation.workflows.patient_conversation import PatientConversationWorkflow, conversation_workflow_id

WORKFLOWS = [PatientConversationWorkflow]

__all__ = ["WORKFLOWS", "PatientConversationWorkflow", "conversation_workflow_id"]
