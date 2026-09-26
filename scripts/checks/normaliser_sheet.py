"""
A review sheet for native speakers: what the voice would be handed for
typical replies, per dialect. `make normaliser-sheet` writes
normaliser-review.csv; a reviewer marks each row right or writes how their
dialect says it, and the fixes go into nafas_conversation.logic.speech.
"""

import csv
from pathlib import Path

from nafas_conversation.logic.speech import speakable
from nafas_core.enums.dialect import SpokenDialect

REPLIES = [
    "موعدك يوم الأربعاء ٣٠ سبتمبر الساعة ٥:٤٠ م.",
    "في مواعيد الساعة ٩:٣٠ ص و١١:١٥ ص و١٢:٤٥ م.",
    "أكّد خلال ١٠ دقايق، وإلا هيتلغى الحجز.",
    "العيادة في شارع ٢٣، الدور ٣، شقة ١١.",
    "الكشف ٤٥٠ جنيه، والاستشارة ٢٠٠.",
    "موعدك بعد ٢ يوم، الساعة 21:00.",
    "سنة ٢٠٢٦ هنبدأ مواعيد يوم السبت.",
]
OUT = Path("normaliser-review.csv")


def rows() -> list[dict]:
    return [
        {
            "dialect": dialect.value,
            "written": reply,
            "spoken": speakable(reply, dialect.value) or "(not spoken)",
            "right?": "",
            "how we say it": "",
        }
        for dialect in SpokenDialect
        for reply in REPLIES
    ]


def main() -> None:
    with OUT.open("w", encoding="utf-8-sig", newline="") as sheet:
        writer = csv.DictWriter(sheet, fieldnames=["dialect", "written", "spoken", "right?", "how we say it"])
        writer.writeheader()
        writer.writerows(rows())
    print(f"{OUT}: {len(REPLIES)} replies in {len(SpokenDialect)} dialects")


if __name__ == "__main__":
    main()
