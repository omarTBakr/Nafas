from nafas_core.exceptions.base import NafasError


class Refusal(NafasError):
    """A refusal the web app acts on by its reason, answered as {"detail", "reason"} like the services' own."""

    def __init__(self, status_code: int, reason: str, detail: str):
        self.status_code = status_code
        self.reason = reason
        self.detail = detail
        super().__init__(f"{status_code} {reason}: {detail}")
