"""Entrypoint: `uv run python -m nafas_consultation.main`, the internal API and the consultation worker in one process."""

import asyncio

from nafas_consultation.activities import ConsultationActivities
from nafas_consultation.api import app
from nafas_consultation.workflows import WORKFLOWS
from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.identity import get_identity
from nafas_core.config import get_setting
from nafas_core.interfaces.llm import get_llm
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.interfaces.stt.factory import get_stt
from nafas_core.logger import setup_logging
from nafas_core.temporal import TaskQueue, serve_with_worker
from nafas_core.tracing import configure_tracing

PORT = 8060


def main() -> None:
    setup_logging()
    configure_tracing()
    activities = ConsultationActivities(
        get_storage(), get_stt(), get_llm(), get_identity(), get_clinical(), get_setting().llm_summary_model
    )
    asyncio.run(
        serve_with_worker(app, port=PORT, task_queue=TaskQueue.CONSULTATION, workflows=WORKFLOWS, activities=activities.all())
    )


if __name__ == "__main__":
    main()
