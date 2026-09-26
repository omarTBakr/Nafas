"""
The dialect-router on our own labelled sentences. `make check-dialects SAMPLES=path/to/samples.csv`.

samples.csv has columns text, dialect (the router's codes: eg, sa, lb, ...).
Reports accuracy per dialect, what each is mistaken for, and how often the
low-confidence flag catches a wrong answer; writes dialect-report.md beside
the samples. The router only ever suggests a dialect and tags analytics:
this decides whether even that is worth keeping on.
"""

import argparse
import asyncio
import csv
from collections import Counter, defaultdict
from pathlib import Path

from nafas_core.config import get_setting
from nafas_core.interfaces.dialect.http import HttpDialectClassifier

BATCH = 32


def report(rows: list[tuple[str, str, bool]]) -> str:
    """rows: (expected, predicted, low_confidence)."""
    by_dialect: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for expected, predicted, low in rows:
        by_dialect[expected].append((predicted, low))

    lines = ["| dialect | samples | accuracy | mistaken for |", "| --- | --- | --- | --- |"]
    for dialect, results in sorted(by_dialect.items()):
        right = sum(1 for predicted, _ in results if predicted == dialect)
        wrong = Counter(predicted for predicted, _ in results if predicted != dialect)
        confused = ", ".join(f"{d} ×{n}" for d, n in wrong.most_common(3)) or "-"
        lines.append(f"| {dialect} | {len(results)} | {right / len(results):.2f} | {confused} |")

    wrong_rows = [(e, p, low) for e, p, low in rows if e != p]
    caught = sum(1 for *_, low in wrong_rows if low)
    right_flagged = sum(1 for e, p, low in rows if e == p and low)
    overall = sum(1 for e, p, _ in rows if e == p) / len(rows) if rows else 0.0
    lines += [
        "",
        f"Overall accuracy {overall:.2f} on {len(rows)} sentences.",
        f"Of {len(wrong_rows)} wrong answers, the low-confidence flag caught {caught}; "
        f"it also flagged {right_flagged} right ones.",
    ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", type=Path)
    parser.add_argument("--url", default=get_setting().dialect_router_url)
    args = parser.parse_args()

    with args.samples.open(encoding="utf-8") as f:
        samples = [(row["text"], row["dialect"]) for row in csv.DictReader(f)]
    router = HttpDialectClassifier(args.url)
    rows = []
    for start in range(0, len(samples), BATCH):
        chunk = samples[start : start + BATCH]
        predictions = await router.classify([text for text, _ in chunk])
        rows += [(expected, p.dialect.value, p.low_confidence) for (_, expected), p in zip(chunk, predictions, strict=True)]

    out = args.samples.with_name("dialect-report.md")
    out.write_text(report(rows), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
