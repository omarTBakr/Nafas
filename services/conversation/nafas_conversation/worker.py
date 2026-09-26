"""Entrypoint: `uv run python -m nafas_conversation.worker`."""

import asyncio

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.config import get_setting
from nafas_core.interfaces.llm import get_llm
from nafas_core.logger import setup_logging
from nafas_core.temporal import TaskQueue, run_worker
from nafas_core.tracing import configure_tracing


def main() -> None:
    setup_logging()
    configure_tracing()
    activities = ConversationActivities(get_llm(), get_identity(), get_scheduling(), get_setting().llm_chat_model)
    asyncio.run(run_worker(TaskQueue.CONVERSATION, WORKFLOWS, activities.all()))


if __name__ == "__main__":
    main()
