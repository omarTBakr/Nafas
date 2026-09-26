import logging

import pytest

from nafas_core import redaction


@pytest.mark.parametrize(
    ("line", "clean"),
    [
        ("login failed for sara.m@example.com", "login failed for [email]"),
        ("call +20 100 123 4567 back", "call [number] back"),
        ("patient said: عندي ألم في صدري", "patient said: [text]"),
        (
            "violates check [parameters: ('منى', 'mona@example.com', 'تعبانة')]\n(Background on this error at: x)",
            "violates check [parameters: [redacted]]\n(Background on this error at: x)",
        ),
    ],
)
def test_patient_data_is_redacted(line, clean):
    assert redaction.redact(line) == clean


def test_ids_times_and_years_are_kept():
    line = "turn failed for patient 0c8eed33-4a71-4c55-9157-307b7db514ea at 2026-09-26 17:40 (attempt 3)"

    assert redaction.redact(line) == line


def test_every_logger_and_its_tracebacks_are_cleaned(caplog):
    redaction.install()
    logger = logging.getLogger("some.library")

    try:
        raise ValueError("bad row ('منى علي', 'mona@example.com')")
    except ValueError:
        with caplog.at_level(logging.ERROR):
            logger.exception("insert failed for %s", "mona@example.com")

    [record] = caplog.records
    assert record.getMessage() == "insert failed for [email]"
    assert "منى" not in record.exc_text and "mona@example.com" not in record.exc_text
    assert "ValueError: bad row ('[text]', '[email]')" in record.exc_text


def test_formatters_that_read_the_arguments_still_work():
    """uvicorn's access log unpacks record.args itself; redaction must leave them as arguments."""
    from uvicorn.logging import AccessFormatter

    redaction.install()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/chat/x?email=sara@example.com", "1.1", 200),
        None,
    )

    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)

    assert line == '127.0.0.1:5000 - "GET /api/chat/x?email=[email] HTTP/1.1" 200 OK'
