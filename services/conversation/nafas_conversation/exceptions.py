from nafas_core.exceptions.base import NafasError


class ConversationError(NafasError):
    """A conversation request that cannot be carried out as asked."""


class EscalationNotFoundError(ConversationError):
    """No such escalation for this doctor."""


class EscalationClosedError(ConversationError):
    """The escalation was already answered, closed or expired."""


class MessageNotFoundError(ConversationError):
    """No such assistant reply in this patient's thread with this doctor."""
