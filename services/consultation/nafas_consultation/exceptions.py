from nafas_core.exceptions.base import NafasError


class ConsultationError(NafasError):
    """A consultation request that cannot be carried out as asked."""


class ConsultationNotFoundError(ConsultationError):
    """No such consultation in this doctor's scope."""


class NotUnderCareError(ConsultationError):
    """The patient is not under this doctor's care."""


class WrongStateError(ConsultationError):
    """The consultation is not at a step where this can be done."""
