from nafas_core.exceptions.base import NafasError


class ProviderError(NafasError):
    """An outside service (model, speech-to-text, storage, messaging) failed or is unusable."""


class LLMError(ProviderError):
    """The language model call failed after the SDK's own retries."""


class LLMRefusalError(LLMError):
    """The model declined the request (stop_reason "refusal")."""


class STTError(ProviderError):
    """Speech-to-text failed."""


class StorageError(ProviderError):
    """Object storage failed."""


class ChannelError(ProviderError):
    """Sending to or reading from a messaging channel failed."""
