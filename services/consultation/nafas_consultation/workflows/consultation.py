"""
ConsultationWorkflow: a recorded visit becomes an approved note in the record.

Started when the doctor stops recording. Transcribe the parts, draft the
note, then wait for the doctor: they approve it (with their edits, which the
API stores before signalling) or throw it away. Only an approved note is
filed. A discard at any step before filing deletes the audio and the words.
A step that keeps failing marks the consultation failed with the reason; the
doctor can then discard it or record again.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from nafas_consultation.activities import ConsultationActivities
    from nafas_consultation.schemas import (
        APPROVED_SIGNAL,
        CONSULTATION_WORKFLOW,
        DISCARD_SIGNAL,
        ConsultationRef,
        Failure,
    )

TRANSCRIBE = {
    "start_to_close_timeout": timedelta(minutes=30),
    "heartbeat_timeout": timedelta(minutes=5),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}
DRAFT = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": RetryPolicy(maximum_attempts=3)}
# an approved note is filed however long clinical-records is away: it never gives up
FILE = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=5))}
STEP = {"start_to_close_timeout": timedelta(seconds=60), "retry_policy": RetryPolicy(maximum_interval=timedelta(minutes=1))}


@workflow.defn(name=CONSULTATION_WORKFLOW)
class ConsultationWorkflow:
    def __init__(self) -> None:
        self._approved = False
        self._discarded = False

    @workflow.signal(name=APPROVED_SIGNAL)
    def approved(self) -> None:
        self._approved = True

    @workflow.signal(name=DISCARD_SIGNAL)
    def discard(self) -> None:
        self._discarded = True

    async def _throw_away(self, ref: ConsultationRef) -> str:
        await workflow.execute_activity_method(ConsultationActivities.discard, ref, **STEP)
        return "discarded"

    @workflow.run
    async def run(self, ref: ConsultationRef) -> str:
        try:
            await workflow.execute_activity_method(ConsultationActivities.transcribe, ref, **TRANSCRIBE)
            if self._discarded:
                return await self._throw_away(ref)
            await workflow.execute_activity_method(ConsultationActivities.draft, ref, **DRAFT)
        except ActivityError as failed:
            if self._discarded:
                return await self._throw_away(ref)
            cause = failed.cause.message if failed.cause else str(failed)
            await workflow.execute_activity_method(
                ConsultationActivities.mark_failed, Failure(ref.consultation_id, ref.doctor_id, cause), **STEP
            )
            return "failed"

        await workflow.wait_condition(lambda: self._approved or self._discarded)
        if self._discarded:
            return await self._throw_away(ref)
        await workflow.execute_activity_method(ConsultationActivities.file, ref, **FILE)
        return "approved"
