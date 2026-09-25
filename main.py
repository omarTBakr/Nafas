from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from activities import ACTIVITIES
from utils.config import get_setting
from utils.create_worker import create_worker
from utils.logger import get_logger, setup_logging
from workflows import WORKFLOWS

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Optionally runs the Temporal worker alongside the API.

    With RUN_WORKER_IN_API set, one process serves requests and executes
    workflows, which is convenient locally. Leave it off anywhere else and run
    `worker.py` separately: slow work then cannot starve request handling, and
    in-flight work survives an API restart.

    Run exactly one generation of workers against a task queue. Two processes
    on the same queue built from different revisions will each decode the
    other's payloads with its own schema, and quietly drop the fields it does
    not know about.
    """
    settings = get_setting()

    if not settings.run_worker_in_api:
        logger.info("worker not started in-process; run worker.py separately")
        yield
        return

    worker = await create_worker(WORKFLOWS, ACTIVITIES)

    logger.info("worker running inside the API on %r", worker.task_queue)

    async with worker:
        yield


app = FastAPI(title="Nafas", description="A Temporal and FastAPI backend", lifespan=lifespan)

# routers are included here; anything that must apply to all of them — an auth
# dependency, say — is attached at inclusion rather than on each endpoint
# app.include_router(thing_router)


@app.get("/health")
async def health() -> dict:
    """Open on purpose: a monitor should not need a secret to see we are alive."""
    return {"status": "ok"}


def main() -> None:
    setup_logging()
    settings = get_setting()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
