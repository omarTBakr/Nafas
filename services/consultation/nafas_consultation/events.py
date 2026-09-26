"""Telling a consultation's workflow what the doctor did. Starting it returns False when Temporal could not be told."""

from typing import Protocol

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from nafas_consultation.schemas import (
    APPROVED_SIGNAL,
    CONSULTATION_WORKFLOW,
    DISCARD_SIGNAL,
    ConsultationRef,
    consultation_workflow_id,
)
from nafas_core.logger import get_logger
from nafas_core.temporal import TaskQueue, get_temporal_client

logger = get_logger(__name__)


class ConsultationEvents(Protocol):
    async def finished(self, consultation_id: str, doctor_id: str) -> bool: ...

    async def approved(self, consultation_id: str) -> bool: ...

    async def discarded(self, consultation_id: str) -> bool: ...


class TemporalConsultationEvents:
    def __init__(self, client: Client | None = None, task_queue: str = TaskQueue.CONSULTATION):
        self._client = client
        self._task_queue = str(task_queue)

    async def _temporal(self) -> Client:
        return self._client or await get_temporal_client()

    async def finished(self, consultation_id: str, doctor_id: str) -> bool:
        try:
            await (await self._temporal()).start_workflow(
                CONSULTATION_WORKFLOW,
                ConsultationRef(consultation_id, doctor_id),
                id=consultation_workflow_id(consultation_id),
                task_queue=self._task_queue,
                # a consultation whose run failed may be sent again; the API allows it only then
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        except Exception:
            logger.exception("could not start the workflow of consultation %s", consultation_id)
            return False
        return True

    async def _signal(self, consultation_id: str, signal: str) -> bool:
        try:
            await (await self._temporal()).get_workflow_handle(consultation_workflow_id(consultation_id)).signal(signal)
        except Exception:
            logger.exception("could not signal %s to consultation %s", signal, consultation_id)
            return False
        return True

    async def approved(self, consultation_id: str) -> bool:
        return await self._signal(consultation_id, APPROVED_SIGNAL)

    async def discarded(self, consultation_id: str) -> bool:
        return await self._signal(consultation_id, DISCARD_SIGNAL)


_events: ConsultationEvents | None = None


def get_events() -> ConsultationEvents:
    global _events
    if _events is None:
        _events = TemporalConsultationEvents()
    return _events


def set_events(events: ConsultationEvents | None) -> None:
    global _events
    _events = events
