import pytest

from nafas_conversation.logic.speech import number_words, speakable, time_words


@pytest.mark.parametrize(
    ("n", "egyptian", "general"),
    [
        (0, "صفر", "صفر"),
        (3, "تلاتة", "ثلاثة"),
        (11, "حداشر", "إحدى عشر"),
        (20, "عشرين", "عشرين"),
        (45, "خمسة وأربعين", "خمسة وأربعين"),
        (123, "مية وتلاتة وعشرين", "مية وثلاثة وعشرين"),
        (2026, "ألفين وستة وعشرين", "ألفين وستة وعشرين"),
    ],
)
def test_numbers_are_spelled_the_way_each_dialect_says_them(n, egyptian, general):
    assert number_words(n, "eg") == egyptian
    assert number_words(n, "lb") == general


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [
        (17, 0, "خمسة"),
        (17, 15, "خمسة وربع"),
        (17, 30, "خمسة ونص"),
        (17, 45, "ستة إلا ربع"),
        (17, 40, "خمسة وأربعين"),
        (12, 45, "واحد إلا ربع"),
    ],
)
def test_clock_times_are_said_as_people_say_them(hour, minute, spoken):
    assert time_words(hour, minute, "eg") == spoken


def test_a_booking_reply_is_spoken_with_its_time_and_date_in_words():
    said = speakable("تمام، حجزتلك الأربعاء ٣٠ سبتمبر الساعة ٥:٤٠ م. أكّد خلال 10 دقايق.", "eg")

    assert said == "تمام، حجزتلك الأربعاء تلاتين سبتمبر الساعة خمسة وأربعين بالليل. أكّد خلال عشرة دقايق."


def test_a_24_hour_time_gets_its_part_of_the_day_and_an_ambiguous_one_none():
    assert speakable("موعدك 14:00", "sa") == "موعدك اثنين الضهر"
    assert speakable("موعدك 21:15", "sa") == "موعدك تسعة وربع بالليل"
    # 9:30 could be morning or evening: nothing is guessed
    assert speakable("موعدك 09:30", "sa") == "موعدك تسعة ونص"
    assert speakable("موعدك 9:30 ص", "sa") == "موعدك تسعة ونص الصبح"


@pytest.mark.parametrize(
    "text",
    [
        "Your appointment is at 5",
        "خد Panadol بعد الأكل",
        "الجرعة ٥٠٠ مجم مرتين",
        "لازم تكمل العلاج",
        "نتيجة التحليل طبيعية",
        "ممكن تاخد حباية قبل النوم",
    ],
)
def test_latin_script_and_clinical_words_are_never_spoken(text):
    assert speakable(text, "eg") is None
