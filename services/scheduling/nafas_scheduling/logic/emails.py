"""
Appointment emails: what a notice says by email, in the patient's language.

Only the appointment: who with, when (clinic time), in person or online.
Never a reason for the visit or anything clinical, since email is read on
lock screens and shared devices. A confirmation carries an .ics invite.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from nafas_core.interfaces.email import Attachment, Email
from nafas_scheduling.enums import NotificationKind

AR_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

SUBJECTS = {
    NotificationKind.CONFIRMED: {"ar": "تم تأكيد موعدك مع {doctor}", "en": "Your appointment with {doctor} is confirmed"},
    NotificationKind.REMINDER: {"ar": "تذكير: موعدك مع {doctor}", "en": "Reminder: your appointment with {doctor}"},
    NotificationKind.HOLD_EXPIRED: {"ar": "انتهت مهلة الحجز المؤقت مع {doctor}", "en": "Your held time with {doctor} ran out"},
    NotificationKind.CANCELLED_BY_DOCTOR: {"ar": "{doctor} ألغى موعدك", "en": "{doctor} cancelled your appointment"},
}
LINES = {
    NotificationKind.CONFIRMED: {"ar": "موعدك يوم {when}.", "en": "Your appointment is on {when}."},
    NotificationKind.REMINDER: {"ar": "نذكّرك بموعدك يوم {when}.", "en": "A reminder of your appointment on {when}."},
    NotificationKind.HOLD_EXPIRED: {
        "ar": "الوقت اللي حجزته مؤقتًا يوم {when} لم يتم تأكيده، فأصبح متاحًا لغيرك. تقدر تحجز من جديد.",
        "en": "The time you held on {when} was not confirmed, so it is free again. You can book again.",
    },
    NotificationKind.CANCELLED_BY_DOCTOR: {
        "ar": "للأسف تم إلغاء موعدك يوم {when}. تقدر تختار موعدًا آخر.",
        "en": "Sorry, your appointment on {when} was cancelled. You can choose another time.",
    },
}
MODES = {"in_person": {"ar": "في العيادة", "en": "in person"}, "online": {"ar": "أونلاين", "en": "online"}}
# an online visit's confirmation and reminder carry the way in
JOIN = {
    "ar": "رابط الزيارة (يفتح قبل موعدها بربع ساعة): {link}",
    "en": "Your visit's link (it opens 15 minutes before the start): {link}",
}
JOINABLE = {NotificationKind.CONFIRMED, NotificationKind.REMINDER}
FOOTER = {
    "ar": "مواعيدك: {link}\nلإيقاف هذه الرسائل غيّر الإعدادات من صفحة ملفك.",
    "en": "Your appointments: {link}\nTo stop these emails, change the setting on your profile page.",
}


@dataclass
class Recipient:
    email: str
    full_name: str
    language: str


def clinic_time(start: datetime, timezone: str, language: str) -> str:
    """ "Wednesday 30 September, 17:40" at the clinic, or its Arabic form with Arabic digits."""
    local = start.astimezone(ZoneInfo(timezone))
    if language == "en":
        return local.strftime("%A %d %B, %H:%M")
    text = f"{AR_WEEKDAYS[local.weekday()]} {local.day} {AR_MONTHS[local.month - 1]}، الساعة {local:%H:%M}"
    return text.translate(AR_DIGITS)


def invite(appointment_id: str, start: datetime, end: datetime, summary: str, location: str | None = None) -> Attachment:
    """A calendar invite for the appointment, in UTC so every calendar places it right."""
    stamp = "%Y%m%dT%H%M%SZ"
    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Nafas//Appointments//EN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{appointment_id}@nafas",
            f"DTSTAMP:{datetime.now(ZoneInfo('UTC')).strftime(stamp)}",
            f"DTSTART:{start.astimezone(ZoneInfo('UTC')).strftime(stamp)}",
            f"DTEND:{end.astimezone(ZoneInfo('UTC')).strftime(stamp)}",
            f"SUMMARY:{summary}",
            *([f"LOCATION:{location}", f"URL:{location}"] if location else []),
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    return Attachment("appointment.ics", body.encode(), "text/calendar")


def compose(
    *,
    kind: NotificationKind,
    recipient: Recipient,
    doctor_name: str,
    appointment_id: str,
    start: datetime,
    end: datetime,
    mode: str,
    timezone: str,
    web_url: str,
) -> Email:
    language = "en" if recipient.language == "en" else "ar"
    when = f"{clinic_time(start, timezone, language)} ({MODES.get(mode, MODES['in_person'])[language]})"
    greeting = f"Hello {recipient.full_name}," if language == "en" else f"أهلاً {recipient.full_name}،"
    base = web_url.rstrip("/")
    join = [JOIN[language].format(link=f"{base}/visit/{appointment_id}")] if mode == "online" and kind in JOINABLE else []
    text = "\n\n".join(
        [greeting, LINES[kind][language].format(when=when), *join, FOOTER[language].format(link=f"{base}/appointments")]
    )
    subject = SUBJECTS[kind][language].format(doctor=doctor_name)
    location = f"{base}/visit/{appointment_id}" if mode == "online" else None
    attachments = [invite(appointment_id, start, end, subject, location)] if kind is NotificationKind.CONFIRMED else []
    return Email(to=recipient.email, subject=subject, text=text, attachments=attachments)
