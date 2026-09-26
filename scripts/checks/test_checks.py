from scripts.checks.arabic import normalise, word_errors
from scripts.checks.listening_test import page, score
from scripts.checks.normaliser_sheet import rows
from scripts.checks.stt_wer import report


def test_spelling_variants_are_not_counted_as_errors():
    assert normalise("إزَّيك يا دكتورة؟") == normalise("ازيك يا دكتوره")
    assert word_errors("عايز أحجز بكرة", "عايز احجز بكره") == (0, 3)


def test_word_errors_count_each_edit():
    # one substitution, one deletion
    assert word_errors("عايز أحجز بكرة الصبح", "عايز أروح بكرة") == (2, 4)


def test_the_report_flags_a_dialect_worse_than_published_and_decides_english():
    table = report(
        [
            {"dialect": "eg", "edits": 2, "words": 10},
            {"dialect": "tn", "edits": 7, "words": 10},
            {"dialect": "en", "edits": 3, "words": 10},
        ]
    )

    assert "| eg | 1 | 0.200 | 0.270 | as published or better |" in table
    assert "| tn | 1 | 0.700 | 0.480 | worse than published |" in table
    assert "fall back to base turbo for English patients" in table


def test_the_listening_score_reads_the_key_and_decides():
    assert score(["A", "B", "A"], ["A", "B", "same"]) == {
        "v3": 2,
        "v2": 0,
        "same": 1,
        "unanswered": 0,
        "decision": "use v3 for Egyptian",
    }
    assert score(["A", "B"], ["B", None])["decision"] == "keep v2"


def test_the_listening_page_holds_no_key():
    html = page([{"text": "أهلاً", "A": "QUFB", "B": "QkJC"}])

    assert "data:audio/wav;base64,QUFB" in html and "v3" not in html and "v2" not in html


def test_the_review_sheet_covers_every_dialect_and_keeps_clinical_text_out():
    sheet = rows()

    assert {r["dialect"] for r in sheet} >= {"eg", "sa", "ma", "tn", "ye"}
    assert all(r["spoken"] for r in sheet)
    assert not any(ch.isdigit() for r in sheet for ch in r["spoken"] if r["spoken"] != "(not spoken)")


def test_the_dialect_report_shows_confusions_and_what_the_flag_catches():
    from scripts.checks.dialect_router import report

    table = report([("eg", "eg", False), ("eg", "eg", False), ("sy", "ps", True), ("sy", "sy", False), ("sy", "ps", False)])

    assert "| eg | 2 | 1.00 | - |" in table
    assert "| sy | 3 | 0.33 | ps ×2 |" in table
    assert "Of 2 wrong answers, the low-confidence flag caught 1; it also flagged 0 right ones." in table
