"""
EscalationWorkflow: a question waiting for its doctor.

Started by the conversation's workflow when a gate sends a question to the
doctor, and left running when that workflow continues as new. The doctor's
answer is written by the conversation API, which then signals here; this
only keeps time. After `nudge_after_seconds` without an answer the patient
is told it is still waiting (and where to go if it is urgent); after
`expire_after_seconds` the question expires. Both steps re-read the
escalation first, so an answer that arrived without its signal still wins.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from nafas_conversation.activities import ConversationActivities
    from nafas_conversation.schemas import (
        DOCTOR_REPLIED_SIGNAL,
        ESCALATION_WORKFLOW,
        EscalationNotice,
        EscalationStart,
    )

STEP = {"start_to_close_timeout": timedelta(seconds=30), "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1))}


@workflow.defn(name=ESCALATION_WORKFLOW)
class EscalationWorkflow:
    def __init__(self) -> None:
        self._answered = False

    @workflow.signal(name=DOCTOR_REPLIED_SIGNAL)
    def doctor_replied(self) -> None:
        self._answered = True

    async def _wait(self, seconds: int) -> bool:
        """True when the doctor answered within `seconds`."""
        try:
            await workflow.wait_condition(lambda: self._answered, timeout=timedelta(seconds=seconds))
            return True
        except TimeoutError:
            return False

    async def _tell(self, start: EscalationStart, expire: bool) -> bool:
        notice = EscalationNotice(start.escalation_id, start.patient_id, start.doctor_id, str(workflow.uuid4()), expire)
        return await workflow.execute_activity_method(ConversationActivities.tell_patient_about_escalation, notice, **STEP)

    @workflow.run
    async def run(self, start: EscalationStart) -> str:
        if await self._wait(start.nudge_after_seconds):
            return "answered"
        if not await self._tell(start, expire=False):
            return "answered"
        if await self._wait(max(start.expire_after_seconds - start.nudge_after_seconds, 0)):
            return "answered"
        return "expired" if await self._tell(start, expire=True) else "answered"
