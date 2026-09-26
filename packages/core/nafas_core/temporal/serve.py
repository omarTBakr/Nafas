import asyncio
from collections.abc import Sequence

import uvicorn

from nafas_core.logger import get_logger
from nafas_core.temporal.queues import TaskQueue
from nafas_core.temporal.worker import create_worker

logger = get_logger(__name__)

# how long to wait between attempts to reach Temporal before the worker starts
RECONNECT_SECONDS = 5


async def _worker_forever(task_queue: TaskQueue, workflows: Sequence[type], activities: Sequence) -> None:
    """The worker, started once Temporal answers; the API keeps serving while it waits."""
    while True:
        try:
            worker = await create_worker(task_queue, workflows, activities)
            break
        except Exception as exc:  # any failure to connect is retried the same way
            logger.warning("worker on %r waiting for Temporal: %s", str(task_queue), exc)
            await asyncio.sleep(RECONNECT_SECONDS)

    logger.info("worker polling %r", str(task_queue))
    await worker.run()


async def serve_with_worker(
    app, *, port: int, task_queue: TaskQueue, workflows: Sequence[type], activities: Sequence, host: str = "0.0.0.0"
) -> None:
    """
    A service's internal API and its Temporal worker in one process.

    One deployable per service, as PLAN §4 has it; the API answers from the
    first second, and the worker joins when Temporal is reachable. If either
    stops, the process ends, so the orchestrator restarts both together.
    """
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    tasks = [asyncio.create_task(server.serve()), asyncio.create_task(_worker_forever(task_queue, workflows, activities))]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()
