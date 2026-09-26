from nafas_core.exceptions.base import NafasError


class ClinicalError(NafasError):
    """A clinical-records request that cannot be carried out as asked."""


class RecordNotFoundError(ClinicalError):
    """No such document or entry in this scope."""


class NotUnderCareError(ClinicalError):
    """The patient is not under this doctor's care."""
