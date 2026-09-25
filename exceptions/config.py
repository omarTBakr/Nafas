from exceptions.base import NafasError


class ConfigurationError(NafasError):
    """The environment is not usable: a missing variable, a bad value."""


class MissingSettingError(ConfigurationError):
    """A required setting is absent from the environment and the .env file."""


class InvalidSettingError(ConfigurationError):
    """A setting is present but its value cannot be used."""
