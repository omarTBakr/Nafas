from collections.abc import Sequence

from temporalio.client import Client
from temporalio.worker import Worker

from utils.config import get_setting
from utils.logger import get_logger
from utils.temporal_client import get_temporal_client

logger = get_logger(__name__)


async def create_worker(
    workflows: Sequence[type],
    activities: Sequence,
    task_queue: str | None = None,
    client: Client | None = None,
    **worker_kwargs,
) -> Worker:
    """
    Builds a Temporal Worker.

    Connects a client and falls back to TEMPORAL_TASK_QUEUE when no client or
    queue is given, so callers only have to say what to register.

    The worker is returned rather than run, so the caller decides between
    `await worker.run()` and `async with worker:`.
    """
    if client is None:
        client = await get_temporal_client()

    if task_queue is None:
        task_queue = get_setting().temporal_task_queue

    logger.info(
        "creating worker on %r with %d workflow(s) and %d activities",
        task_queue,
        len(workflows),
        len(activities),
    )

    return Worker(
        client,
        task_queue=task_queue,
        workflows=list(workflows),
        activities=list(activities),
        **worker_kwargs,
    )
