from enums.providers import LLMProvider
from interfaces.llm.base import LLM
from utils.config import get_setting

_llm: LLM | None = None


def get_llm() -> LLM:
    """The process-wide LLM for LLM_PROVIDER; one client, so one connection pool."""
    global _llm
    if _llm is None:
        settings = get_setting()
        match settings.llm_provider:
            case LLMProvider.ANTHROPIC:
                from interfaces.llm.claude import AnthropicLLM

                _llm = AnthropicLLM(api_key=settings.anthropic_api_key.get_secret_value())

    return _llm


def set_llm(llm: LLM | None) -> None:
    """Replaces the process-wide LLM; tests pass a FakeLLM, and None to reset."""
    global _llm
    _llm = llm
