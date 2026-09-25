class NafasError(Exception):
    """
    Root of every error this project raises deliberately.

    Catching NafasError catches anything the project itself signalled, and
    lets genuinely unexpected errors (bugs) escape uncaught.
    """
