"""Entrypoint: `uv run python -m nafas_conversation.main`, the internal API and the worker in one process."""

import asyncio

from nafas_conversation.activities import ConversationActivities
from nafas_conversation.api import app
from nafas_conversation.logic.context import ClinicalContext, WebGroundedContext
from nafas_conversation.logic.turn import Models
from nafas_conversation.logic.voice import VoiceProviders
from nafas_conversation.workflows import WORKFLOWS
from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.config import get_setting
from nafas_core.interfaces.dialect.factory import get_dialect_classifier
from nafas_core.interfaces.llm import get_llm
from nafas_core.interfaces.search import get_web_search
from nafas_core.interfaces.storage.factory import get_storage
from nafas_core.interfaces.stt.factory import get_stt
from nafas_core.interfaces.tts import get_tts
from nafas_core.startup import start_service
from nafas_core.temporal import TaskQueue, serve_with_worker

PORT = 8040


def main() -> None:
    start_service("conversation")
    settings = get_setting()
    context = ClinicalContext(get_scheduling(), get_clinical())
    web = get_web_search()
    if web is not None and settings.web_search_patient:
        # general answers may draw on trusted medical sites (docs/PLAN.md §6c)
        context = WebGroundedContext(context, web, get_llm(), settings.llm_classifier_model, settings.web_search_domains)
    activities = ConversationActivities(
        get_llm(),
        get_identity(),
        get_scheduling(),
        Models(chat=settings.llm_chat_model, classifier=settings.llm_classifier_model),
        VoiceProviders(stt=get_stt(), tts=get_tts(), storage=get_storage(), dialects=get_dialect_classifier()),
        context,
    )
    asyncio.run(
        serve_with_worker(app, port=PORT, task_queue=TaskQueue.CONVERSATION, workflows=WORKFLOWS, activities=activities.all())
    )


if __name__ == "__main__":
    main()
