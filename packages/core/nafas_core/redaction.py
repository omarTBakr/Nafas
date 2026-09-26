"""
Patient data kept out of logs.

Our own log lines name ids, never content, but an exception can carry
anything: SQLAlchemy prints a failed statement's parameters (a name, an
email, a message), an HTTP error its request. So every record, from every
logger, is cleaned as it is made, traceback included, before any handler
sees it. Ids stay: they are how a log line is traced, and they reveal
nothing without the database.
"""

import logging
import re
import traceback
from collections.abc import Mapping

REDACTED = "[redacted]"

_PATTERNS = [
    # a failed SQL statement's bound values, whatever they were
    (re.compile(r"\[parameters: .*?\](?=\s*(\(Background|$))", re.S), f"[parameters: {REDACTED}]"),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
    # 8 to 15 digits, bare or in space-separated groups, as phone numbers are
    # written; dates, times and uuids have hyphens or colons and are left alone
    (re.compile(r"(?<![\w:.-])\+?\d(?: ?\d){7,14}(?![\w:.-])"), "[number]"),
    # our log lines are English: any Arabic in one came from a person
    (re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+(?:[\s،؟]+[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]+)*"), "[text]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _clean(value):
    # strings are cleaned; anything else a formatter needs (numbers, a status code) is kept
    return redact(value) if isinstance(value, str) else value


_installed = False


def install() -> None:
    """Cleans every log record from here on, in this process. Idempotent."""
    global _installed
    if _installed:
        return
    make_record = logging.getLogRecordFactory()

    def redacted_record(*args, **kwargs) -> logging.LogRecord:
        record = make_record(*args, **kwargs)
        # the template and each argument are cleaned where they are, so formatters
        # that read record.args themselves (uvicorn's access log) still work
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if isinstance(record.args, Mapping):
                record.args = {k: _clean(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_clean(v) for v in record.args)
        except Exception:
            # a message that cannot even be cleaned is dropped, not printed raw
            record.msg, record.args = "[unredactable log message]", ()
        if record.exc_info and record.exc_info[0] is not None:
            # formatted now, cleaned, and cached where every Formatter looks first
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return record

    logging.setLogRecordFactory(redacted_record)
    _installed = True
