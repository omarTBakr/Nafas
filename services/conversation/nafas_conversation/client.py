"""Sending a patient's message into their conversation, for whatever receives it (the gateway's chat route)."""

from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy

from nafas_conversation.schemas import ChatReply, ConversationStart, PatientMessage
from nafas_conversation.workflows import PatientConversationWorkflow, conversation_workflow_id
from nafas_core.temporal import TaskQueue


async def send_patient_message(
    client: Client, *, patient_id: str, doctor_id: str, text: str, task_queue: str = TaskQueue.CONVERSATION
) -> ChatReply:
    """
    Delivers one message and waits for the reply, starting the conversation's
    workflow if none is running. Raises WorkflowUpdateFailedError for a
    message the workflow refuses (empty, too long).
    """
    start = WithStartWorkflowOperation(
        PatientConversationWorkflow.run,
        ConversationStart(patient_id=patient_id, doctor_id=doctor_id),
        id=conversation_workflow_id(doctor_id, patient_id),
        task_queue=str(task_queue),
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await client.execute_update_with_start_workflow(
        PatientConversationWorkflow.send_message, PatientMessage(text), start_workflow_operation=start
    )
