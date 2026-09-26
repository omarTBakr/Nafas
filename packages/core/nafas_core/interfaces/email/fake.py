from nafas_core.interfaces.email.base import Email


class FakeEmailSender:
    """Keeps every email instead of sending it."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[Email] = []

    async def send(self, email: Email) -> bool:
        from nafas_core.exceptions.providers import EmailError

        if self.fail:
            raise EmailError("the fake mail server was told to fail")
        self.sent.append(email)
        return True
