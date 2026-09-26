"""Entrypoint: `uv run python -m nafas_scheduling.main`, the internal API and the booking worker in one process."""

import asyncio

from nafas_core.logger import setup_logging
from nafas_core.temporal import TaskQueue, serve_with_worker
from nafas_core.tracing import configure_tracing
from nafas_scheduling.activities import ACTIVITIES
from nafas_scheduling.api import app
from nafas_scheduling.workflows import WORKFLOWS

PORT = 8030


def main() -> None:
    setup_logging()
    configure_tracing()
    asyncio.run(serve_with_worker(app, port=PORT, task_queue=TaskQueue.SCHEDULING, workflows=WORKFLOWS, activities=ACTIVITIES))


if __name__ == "__main__":
    main()
