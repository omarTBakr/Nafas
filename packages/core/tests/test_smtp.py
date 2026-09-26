"""Email through a real SMTP server: Mailpit catches what the sender sends, attachments included."""

import httpx
import pytest

from nafas_core.exceptions.providers import EmailError
from nafas_core.interfaces.email.base import Attachment, Email
from nafas_core.interfaces.email.smtp import DisabledSender, SMTPSender


async def test_a_message_arrives_with_its_subject_text_and_calendar_invite(mailpit):
    sender = SMTPSender("localhost", 1025, "Nafas <no-reply@nafas.test>", starttls=False)
    ics = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    sent = await sender.send(
        Email(
            to="mona@example.com",
            subject="تم تأكيد موعدك مع د. قلب",
            text="أهلاً منى،\n\nموعدك الأربعاء.",
            attachments=[Attachment("appointment.ics", ics, "text/calendar")],
        )
    )

    assert sent is True
    [summary] = httpx.get(f"{mailpit}/api/v1/messages", timeout=5).json()["messages"]
    message = httpx.get(f"{mailpit}/api/v1/message/{summary['ID']}", timeout=5).json()
    assert message["Subject"] == "تم تأكيد موعدك مع د. قلب"
    assert message["To"][0]["Address"] == "mona@example.com" and message["From"]["Address"] == "no-reply@nafas.test"
    assert "موعدك الأربعاء" in message["Text"]
    assert [a["FileName"] for a in message["Attachments"]] == ["appointment.ics"]


async def test_an_unreachable_server_is_an_email_error_not_a_crash():
    with pytest.raises(EmailError, match="could not be reached"):
        await SMTPSender("127.0.0.1", 1, "Nafas <n@n.test>", starttls=False).send(Email(to="a@b.test", subject="s", text="t"))


async def test_with_email_off_nothing_is_sent_and_the_caller_can_tell():
    assert await DisabledSender().send(Email(to="a@b.test", subject="s", text="t")) is False
