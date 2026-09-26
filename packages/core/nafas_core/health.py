"""What /health reports: alive, and exactly which build and configuration is answering (PLAN.md §6b, reproducible config)."""

from nafas_core.config import get_setting


def health_info(service: str, **details) -> dict:
    """
    The service, its environment and commit, the model IDs it would call, and
    whatever the service adds (its prompt versions, its pinned weights). Never
    a secret: only names and versions.
    """
    settings = get_setting()
    return {
        "status": "ok",
        "service": service,
        "environment": settings.environment.value,
        "version": settings.git_sha or "unversioned",
        "models": {
            "chat": settings.llm_chat_model,
            "classifier": settings.llm_classifier_model,
            "summary": settings.llm_summary_model,
        },
        **details,
    }
