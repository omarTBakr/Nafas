from nafas_core.exceptions.base import NafasError


class IdentityError(NafasError):
    """An identity request that cannot be carried out as asked."""


class AccountExistsError(IdentityError):
    """An account with this email already exists."""


class UnknownSpecializationError(IdentityError):
    """No specialization has this code; seed them first (`python -m nafas_identity.cli seed`)."""


class WeakPasswordError(IdentityError):
    """The password is too short to protect patient records."""
