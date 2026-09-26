"""
Text made safe and speakable before the tts service hears it.

`speakable` returns None for anything that must stay text only: Latin
script (drug names, English, codes the voice would garble) or clinical
words (doses, medicines, diagnoses). Otherwise it spells out numbers,
clock times and years as words, the way the reply's dialect says them. The
model never does this: a model that writes "5:40" is read correctly because
code, not the model, turns it into words.

Two spellings of the numbers: Egyptian (and Sudanese), and a near-formal set
understood across the other dialects. Truly dialect-specific counting
(Maghrebi "جوج" for two, Levantine "طنعش" for twelve) is not covered yet.
"""

import re

# Arabic-Indic and Eastern Arabic-Indic digits, as the model or the patient may write them
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LATIN = re.compile(r"[A-Za-z]")
_TIME = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)(\s*(?:م|ص)(?![؀-ۿ]))?")
_NUMBER = re.compile(r"(?<![\d:])\d+(?![\d:])")

# words that make a message clinical: it is never spoken, only shown
CLINICAL = re.compile(
    r"(مجم|ملجم|ملغ|مليجرام|جرع(ه|ة)|حب(ه|ة|ايه|اية)|اقراص|أقراص|قرص|دوا|دواء|ادوي(ه|ة)|أدوي(ه|ة)|علاج|"
    r"تشخيص|تحليل|نتيج(ه|ة)\s*التحليل|مضاد\s*حيوي|انسولين|أنسولين|ضغط\s*الدم|سكر\s*الدم|اشع(ه|ة)|أشع(ه|ة))"
)

EGYPTIAN = {"eg", "sd"}

_WORDS = {
    "eg": {
        "units": ["صفر", "واحد", "اتنين", "تلاتة", "أربعة", "خمسة", "ستة", "سبعة", "تمانية", "تسعة"],
        "teens": ["عشرة", "حداشر", "اتناشر", "تلتاشر", "أربعتاشر", "خمستاشر", "ستاشر", "سبعتاشر", "تمنتاشر", "تسعتاشر"],
        "tens": ["", "", "عشرين", "تلاتين", "أربعين", "خمسين", "ستين", "سبعين", "تمانين", "تسعين"],
        "hundreds": ["", "مية", "ميتين", "تلتمية", "ربعمية", "خمسمية", "ستمية", "سبعمية", "تمنمية", "تسعمية"],
    },
    "general": {
        "units": ["صفر", "واحد", "اثنين", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"],
        "teens": [
            "عشرة",
            "إحدى عشر",
            "اثنا عشر",
            "ثلاثة عشر",
            "أربعة عشر",
            "خمسة عشر",
            "ستة عشر",
            "سبعة عشر",
            "ثمانية عشر",
            "تسعة عشر",
        ],
        "tens": ["", "", "عشرين", "ثلاثين", "أربعين", "خمسين", "ستين", "سبعين", "ثمانين", "تسعين"],
        "hundreds": ["", "مية", "ميتين", "ثلاثمية", "أربعمية", "خمسمية", "ستمية", "سبعمية", "ثمانمية", "تسعمية"],
    },
}


def _words(dialect: str | None) -> dict:
    return _WORDS["eg" if dialect in EGYPTIAN else "general"]


def number_words(n: int, dialect: str | None) -> str:
    """0 to 9999 as spoken words; larger numbers are read digit by digit."""
    w = _words(dialect)
    if n < 10:
        return w["units"][n]
    if n < 20:
        return w["teens"][n - 10]
    if n < 100:
        tens, unit = divmod(n, 10)
        return w["tens"][tens] if unit == 0 else f"{w['units'][unit]} و{w['tens'][tens]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = w["hundreds"][hundreds]
        return head if rest == 0 else f"{head} و{number_words(rest, dialect)}"
    if n < 10000:
        thousands, rest = divmod(n, 1000)
        head = {1: "ألف", 2: "ألفين"}.get(thousands) or f"{w['units'][thousands]} آلاف"
        return head if rest == 0 else f"{head} و{number_words(rest, dialect)}"
    return " ".join(w["units"][int(d)] for d in str(n))


def time_words(hour: int, minute: int, dialect: str | None) -> str:
    """A clock time as people say it: "خمسة ونص", "ستة إلا ربع", "خمسة وأربعين"."""
    twelve = hour % 12 or 12
    spoken = number_words(twelve, dialect)
    if minute == 0:
        return spoken
    if minute == 15:
        return f"{spoken} وربع"
    if minute == 30:
        return f"{spoken} ونص"
    if minute == 45:
        return f"{number_words(twelve % 12 + 1, dialect)} إلا ربع"
    return f"{spoken} و{number_words(minute, dialect)}"


def _part_of_day(hour: int) -> str:
    if hour < 12:
        return "الصبح"
    if hour < 17:
        return "الضهر"
    return "بالليل"


def speakable(text: str, dialect: str | None) -> str | None:
    """The text, with numbers and times as words, ready for the voice; None if it must stay text only."""
    text = text.translate(_DIGITS)
    if _LATIN.search(text) or CLINICAL.search(text):
        return None

    def spell_time(match: re.Match) -> str:
        hour, minute, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
        if hour > 23 or minute > 59:
            return match.group(0)
        if suffix:
            # the text said morning or evening
            part = "الصبح" if suffix.strip() == "ص" else "بالليل" if hour % 12 >= 5 else "الضهر"
        elif hour == 0 or hour > 12:
            # a 24-hour time settles it
            part = _part_of_day(hour)
        else:
            # "5:40" alone could be either; saying a part of the day would be a guess
            return time_words(hour, minute, dialect)
        return f"{time_words(hour, minute, dialect)} {part}"

    text = _TIME.sub(spell_time, text)
    text = _NUMBER.sub(lambda m: number_words(int(m.group(0)), dialect), text)
    return re.sub(r"\s+", " ", text).strip()
