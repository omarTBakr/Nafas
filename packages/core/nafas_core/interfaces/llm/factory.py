from nafas_core.config import get_setting
from nafas_core.enums.providers import LLMProvider
from nafas_core.interfaces.llm.base import LLM

_llm: LLM | None = None


def get_llm() -> LLM:
    """The process-wide LLM for LLM_PROVIDER; one client, so one connection pool."""
    global _llm
    if _llm is None:
        settings = get_setting()
        match settings.llm_provider:
            case LLMProvider.ANTHROPIC:
                from nafas_core.interfaces.llm.claude import AnthropicLLM

                _llm = AnthropicLLM(
                    api_key=settings.anthropic_api_key.get_secret_value(),
                    workspace_id=settings.anthropic_workspace_id,
                )

    return _llm


def set_llm(llm: LLM | None) -> None:
    """Replaces the process-wide LLM; tests pass a FakeLLM, and None to reset."""
    global _llm
    _llm = llm
