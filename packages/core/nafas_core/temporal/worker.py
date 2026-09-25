from collections.abc import Sequence

from temporalio.client import Client
from temporalio.worker import Worker

from nafas_core.logger import get_logger
from nafas_core.temporal.client import get_temporal_client
from nafas_core.temporal.queues import TaskQueue

logger = get_logger(__name__)


async def create_worker(
    task_queue: TaskQueue,
    workflows: Sequence[type],
    activities: Sequence,
    client: Client | None = None,
    **worker_kwargs,
) -> Worker:
    """
    Builds a Temporal Worker for one service's queue.

    The worker is returned rather than run, so the caller decides between
    `await worker.run()` and `async with worker:`.
    """
    if client is None:
        client = await get_temporal_client()

    logger.info(
        "creating worker on %r with %d workflow(s) and %d activities",
        str(task_queue),
        len(workflows),
        len(activities),
    )

    return Worker(
        client,
        task_queue=str(task_queue),
        workflows=list(workflows),
        activities=list(activities),
        **worker_kwargs,
    )


async def run_worker(task_queue: TaskQueue, workflows: Sequence[type], activities: Sequence) -> None:
    """
    Runs a service's worker until cancelled; each service's `worker.py` calls this.

    Refuses to start with nothing registered: such a worker polls forever and
    does nothing, which looks exactly like one that is merely idle.
    """
    if not workflows and not activities:
        logger.error("nothing to register on %r: add workflows or activities first", str(task_queue))
        return

    worker = await create_worker(task_queue, workflows, activities)

    logger.info("worker polling %r", str(task_queue))
    await worker.run()
