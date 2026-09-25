"""Entrypoint for the Temporal worker: `uv run worker.py`.

Kept at the project root so the working directory lands on sys.path. It
registers whatever `workflows.WORKFLOWS` and `activities.ACTIVITIES` hold, so
adding work is an edit to those lists and never to this file.
"""

import asyncio

from activities import ACTIVITIES
from utils.create_worker import create_worker
from utils.logger import get_logger, setup_logging
from utils.tracing import configure_tracing
from workflows import WORKFLOWS

logger = get_logger(__name__)


async def run() -> None:
    if not WORKFLOWS and not ACTIVITIES:
        # a worker with nothing registered polls forever and does nothing,
        # which looks identical to a worker that is merely idle
        logger.error("nothing to register: add to workflows.WORKFLOWS and activities.ACTIVITIES first")
        return

    worker = await create_worker(WORKFLOWS, ACTIVITIES)

    logger.info("worker polling %r", worker.task_queue)
    await worker.run()


def main() -> None:
    setup_logging()
    configure_tracing()
    asyncio.run(run())


if __name__ == "__main__":
    main()
