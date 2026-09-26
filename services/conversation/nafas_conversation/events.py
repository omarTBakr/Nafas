"""
What the API tells an EscalationWorkflow after the database has changed:
the doctor answered, so its timers stop. Best effort, like scheduling's:
the workflow re-reads the escalation before nudging, so a lost signal costs
nothing but a timer that finds the question answered.
"""

from typing import Protocol

from temporalio.client import Client

from nafas_conversation.models import Escalation
from nafas_conversation.schemas import DOCTOR_REPLIED_SIGNAL
from nafas_core.logger import get_logger
from nafas_core.temporal import get_temporal_client

logger = get_logger(__name__)


class EscalationEvents(Protocol):
    async def answered(self, escalation: Escalation) -> None: ...


class TemporalEscalationEvents:
    def __init__(self, client: Client | None = None):
        self._client = client

    async def answered(self, escalation: Escalation) -> None:
        if not escalation.workflow_id:
            return
        try:
            client = self._client or await get_temporal_client()
            await client.get_workflow_handle(escalation.workflow_id).signal(DOCTOR_REPLIED_SIGNAL)
        except Exception:
            logger.exception("could not signal %s", escalation.workflow_id)


_events: EscalationEvents | None = None


def get_events() -> EscalationEvents:
    global _events
    if _events is None:
        _events = TemporalEscalationEvents()
    return _events


def set_events(events: EscalationEvents | None) -> None:
    global _events
    _events = events
