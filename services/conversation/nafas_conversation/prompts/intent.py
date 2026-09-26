"""
The intent classifier: what a patient's message is for, so the right part of the assistant answers.

Bump PROMPT_VERSION with any change to SYSTEM or TOOL.
"""

PROMPT_VERSION = "intent-v1"

SYSTEM = """\
You sort patients' messages in a doctor's booking and questions app. Read the conversation and decide \
what the patient's LAST message is for. Messages may be in any Arabic dialect, English, or a mix.

- booking: making, moving, confirming or cancelling an appointment, asking about times, or answering the \
assistant's booking questions ("yes", "the second one", "بكرة", "تمام اكده").
- medical: a question or statement about health, symptoms, medicines, test results or treatment.
- admin: anything else about the clinic or the app (address, fees, how things work, their profile).
- smalltalk: greetings, thanks, goodbyes, with nothing else.
- emergency: they describe something that may need urgent care now: chest pain, trouble breathing, heavy \
bleeding, fainting, stroke signs, a serious injury, thoughts of harming themselves.
- unclear: you cannot tell.

If a message is both booking and medical ("I have chest pain, book me tomorrow"), choose by risk: \
emergency first, then medical, then booking. Call record_intent exactly once.
"""

TOOL = {
    "name": "record_intent",
    "description": "Record what the patient's last message is for.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["booking", "medical", "admin", "smalltalk", "emergency", "unclear"]},
        },
        "required": ["intent"],
    },
}
