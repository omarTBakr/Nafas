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

MEDICAL_NOT_YET = {
    "ar": (
        "أنا مساعد آلي وبساعد في المواعيد بس دلوقتي، ومقدرش أجاوب على أسئلة طبية. "
        "اسأل الدكتور في الزيارة، ولو حاسس إن الموضوع مستعجل روح أقرب طوارئ."
    ),
    "en": (
        "I am an AI assistant and for now I can only help with appointments, not medical questions. "
        "Please ask the doctor at your visit, and if it feels urgent, go to the nearest emergency room."
    ),
}


NOT_HEARD = {
    "ar": "معلش، مقدرتش أسمع الرسالة الصوتية كويس. ممكن تسجلها تاني أو تكتبها؟",
    "en": "Sorry, I could not make out that voice note. Could you record it again, or type it?",
}


def pick(replies: dict[str, str], language: str) -> str:
    return replies["en" if language == "en" else "ar"]
