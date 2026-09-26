"""Entrypoint: `uv run python -m nafas_clinical.main`, the internal API and the ingestion worker in one process."""

import asyncio

from nafas_clinical.activities import ClinicalActivities
from nafas_clinical.api import app
from nafas_clinical.workflows import WORKFLOWS
from nafas_core.config import get_setting
from nafas_core.interfaces.embeddings import get_embeddings
from nafas_core.interfaces.llm import get_llm
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.startup import start_service
from nafas_core.temporal import TaskQueue, serve_with_worker

PORT = 8050


def main() -> None:
    start_service("clinical-records")
    activities = ClinicalActivities(get_storage(), get_embeddings(), get_llm(), get_setting().llm_chat_model)
    asyncio.run(
        serve_with_worker(app, port=PORT, task_queue=TaskQueue.CLINICAL, workflows=WORKFLOWS, activities=activities.all())
    )


if __name__ == "__main__":
    main()
