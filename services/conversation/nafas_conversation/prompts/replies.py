"""
Fixed replies: said word for word, never written by a model.

An emergency gets the same words every time, whatever any model thinks.
Each set carries a version, recorded on the message like a prompt's.
"""

VERSION = "replies-v1"

EMERGENCY = {
    "ar": (
        "اللي بتوصفه ممكن يكون حالة طارئة. من فضلك اتصل بالإسعاف على ١٢٣ دلوقتي، أو روح أقرب طوارئ حالاً. "
        "ما تستناش رد من العيادة. أنا مساعد آلي ومش دكتور."
    ),
    "en": (
        "What you describe may be an emergency. Please call an ambulance on 123 now, or go to the nearest "
        "emergency room straight away. Do not wait for a reply from the clinic. I am an AI assistant, not a doctor."
    ),
}

NOT_HEARD = {
    "ar": "معلش، مقدرتش أسمع الرسالة الصوتية كويس. ممكن تسجلها تاني أو تكتبها؟",
    "en": "Sorry, I could not make out that voice note. Could you record it again, or type it?",
}


ESCALATED = {
    "ar": (
        "سؤالك محتاج رد {doctor} شخصيًا، فبعتّه له. هتلاقي رده هنا في المحادثة. "
        "لو حاسس إن الموضوع مستعجل، روح أقرب طوارئ أو اتصل بـ ١٢٣."
    ),
    "en": (
        "Your question needs {doctor} personally, so I have sent it to them. You will find their answer here in "
        "this chat. If it feels urgent, go to the nearest emergency room or call 123."
    ),
}

NEEDS_VISIT = {
    "ar": "أقدر أساعد في الأسئلة الطبية العامة بعد ما يكون عندك موعد مؤكد مع الدكتور. تحب أحجزلك موعد؟",
    "en": "I can help with general medical questions once you have a confirmed appointment with the doctor. Shall I book one?",
}

ESCALATION_NUDGE = {
    "ar": "{doctor} لسه ما ردش على سؤالك. لو حاسس إن الموضوع مستعجل، روح أقرب طوارئ أو اتصل بـ ١٢٣.",
    "en": "{doctor} has not answered your question yet. If it feels urgent, go to the nearest emergency room or call 123.",
}

ESCALATION_EXPIRED = {
    "ar": "للأسف {doctor} ما لحقش يرد على سؤالك. ممكن تحجز موعد وتسأله في الزيارة، ولو مستعجل روح الطوارئ.",
    "en": (
        "Sorry, {doctor} could not answer your question in time. You could book a visit and ask there; "
        "if it is urgent, go to the emergency room."
    ),
}


def pick(replies: dict[str, str], language: str) -> str:
    return replies["en" if language == "en" else "ar"]
