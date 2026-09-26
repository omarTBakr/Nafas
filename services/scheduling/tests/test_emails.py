from datetime import UTC, datetime

from nafas_scheduling.enums import NotificationKind
from nafas_scheduling.logic.emails import Recipient, clinic_time, compose

START = datetime(2026, 9, 30, 14, 40, tzinfo=UTC)
END = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)


def email(kind=NotificationKind.CONFIRMED, language="ar"):
    return compose(
        kind=kind,
        recipient=Recipient("mona@example.com", "منى", language),
        doctor_name="د. قلب" if language == "ar" else "Dr Heart",
        appointment_id="a1",
        start=START,
        end=END,
        mode="in_person",
        timezone="Africa/Cairo",
        web_url="https://nafas.example/",
    )


def test_times_are_clinic_time_in_the_patients_language():
    assert clinic_time(START, "Africa/Cairo", "en") == "Wednesday 30 September, 17:40"
    assert clinic_time(START, "Africa/Cairo", "ar") == "الأربعاء ٣٠ سبتمبر، الساعة ١٧:٤٠"


def test_a_confirmation_says_who_and_when_and_carries_a_calendar_invite():
    sent = email()

    assert sent.to == "mona@example.com"
    assert sent.subject == "تم تأكيد موعدك مع د. قلب"
    assert "الأربعاء ٣٠ سبتمبر، الساعة ١٧:٤٠ (في العيادة)" in sent.text
    assert "https://nafas.example/appointments" in sent.text
    [invite] = sent.attachments
    ics = invite.content.decode()
    assert invite.mime_type == "text/calendar"
    # in UTC, so any calendar places it at 17:40 Cairo
    assert "DTSTART:20260930T144000Z" in ics and "DTEND:20260930T150000Z" in ics and "UID:a1@nafas" in ics


def test_other_notices_have_their_own_words_and_no_invite():
    reminder = email(NotificationKind.REMINDER, "en")
    lapsed = email(NotificationKind.HOLD_EXPIRED, "en")

    assert reminder.subject == "Reminder: your appointment with Dr Heart" and reminder.attachments == []
    assert "was not confirmed, so it is free again" in lapsed.text
