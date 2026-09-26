import pytest

from nafas_clinical.logic.chunking import split_text
from nafas_clinical.logic.extraction import ExtractionError, extract, ocr_available

from .conftest import png, scanned_pdf, text_pdf

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="OCR needs tesseract (apt install tesseract-ocr tesseract-ocr-ara)")


async def test_a_pdf_with_text_is_read_without_ocr():
    extracted = await extract(text_pdf(["Echocardiogram report", "Ejection fraction 55 percent"]), "application/pdf")

    assert extracted.page_count == 1 and extracted.ocr_pages == []
    assert "Ejection fraction 55 percent" in extracted.text


@needs_ocr
async def test_a_scanned_pdf_page_is_read_by_ocr():
    extracted = await extract(scanned_pdf(["LIPID PANEL", "LDL 162 mg/dL"]), "application/pdf")

    assert extracted.ocr_pages == [1]
    assert "LIPID PANEL" in extracted.text and "162" in extracted.text


@needs_ocr
async def test_an_image_is_read_by_ocr():
    extracted = await extract(png(["PRESCRIPTION", "Bisoprolol 5 mg"]), "image/png")

    assert "Bisoprolol" in extracted.text


async def test_a_file_that_is_not_what_it_says_is_refused():
    with pytest.raises(ExtractionError):
        await extract(b"not a pdf at all", "application/pdf")
    with pytest.raises(ExtractionError):
        await extract(b"...", "application/zip")


def test_passages_end_at_sentences_and_overlap():
    text = " ".join(f"Sentence number {i} says something about the heart." for i in range(60))

    passages = split_text(text, max_chars=300, overlap=80)

    assert all(len(p) <= 300 for p in passages)
    assert all(p.endswith(".") for p in passages)
    # each passage starts with the tail of the one before
    assert all(prev.split()[-1] in nxt for prev, nxt in zip(passages, passages[1:], strict=False))


def test_arabic_sentences_split_on_arabic_question_marks():
    passages = split_text("هل الضغط عالي؟ نعم قليلا. نراجع الأسبوع القادم.", max_chars=25, overlap=0)

    # whole sentences are packed up to the limit, and cut only after an Arabic or Latin stop
    assert passages == ["هل الضغط عالي؟ نعم قليلا.", "نراجع الأسبوع القادم."]
