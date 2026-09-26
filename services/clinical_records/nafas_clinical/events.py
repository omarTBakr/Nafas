"""Starting a document's ingestion once its file is in storage. Best effort: a document left 'uploaded' can be re-sent."""

from typing import Protocol

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from nafas_clinical.schemas import INGESTION_WORKFLOW, DocumentRef, ingestion_workflow_id
from nafas_core.logger import get_logger
from nafas_core.temporal import TaskQueue, get_temporal_client

logger = get_logger(__name__)


class IngestionEvents(Protocol):
    async def uploaded(self, document_id: str, doctor_id: str) -> bool: ...


class TemporalIngestionEvents:
    def __init__(self, client: Client | None = None, task_queue: str = TaskQueue.CLINICAL):
        self._client = client
        self._task_queue = str(task_queue)

    async def uploaded(self, document_id: str, doctor_id: str) -> bool:
        try:
            client = self._client or await get_temporal_client()
            await client.start_workflow(
                INGESTION_WORKFLOW,
                DocumentRef(document_id, doctor_id),
                id=ingestion_workflow_id(document_id),
                task_queue=self._task_queue,
                # re-sending a failed document runs it again
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        except Exception:
            logger.exception("could not start ingestion of %s", document_id)
            return False
        return True


_events: IngestionEvents | None = None


def get_events() -> IngestionEvents:
    global _events
    if _events is None:
        _events = TemporalIngestionEvents()
    return _events


def set_events(events: IngestionEvents | None) -> None:
    global _events
    _events = events
