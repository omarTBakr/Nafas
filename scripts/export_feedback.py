"""
The feedback export: what patients and doctors told us, as de-identified
datasets for evals and prompt work. `make export-feedback` (or
`uv run python -m scripts.export_feedback --out data/feedback`).

Only patients who gave the optional service_improvement consent, and only
while it is in force, are read. Everything written is de-identified here:
ids become salted pseudonyms (FEEDBACK_SALT, kept out of the output), and the
names we know (the patient's, every doctor's), emails, phone and id numbers
and written dates are replaced in the text. That is not a guarantee: free
text can name anyone. So every file is marked for human review, and nothing
goes into an eval set or a training run until a person has read it.

Four files:
- chat_ratings.jsonl: a rated assistant reply, the question it answered, what wrote it
- escalations.jsonl: a question the assistant sent to the doctor, and the doctor's answer
- visit_notes.jsonl: a visit's transcript, the model's draft and the note the doctor approved
- eval_candidates.jsonl: questions for a clinician to label into evals/safety.jsonl
  (thumbs-down replies, and questions a gate sent on because it could not decide)

It runs as the schema owner, past row-level security, because it reads
across services; the run itself is written to the audit log.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_core.config import get_setting

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# 7 or more digits, Latin or Arabic-Indic, bare or in groups: phones, national ids, file numbers
NUMBER = re.compile(r"(?<![\w.])[+]?[\d٠-٩](?:[\s-]?[\d٠-٩]){6,}(?![\w.])")
DATE = re.compile(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b|[٠-٩]{1,4}/[٠-٩]{1,2}/[٠-٩]{1,4}")
# a name part shorter than this is too likely to be an ordinary word
MIN_NAME_PART = 3


def pseudonym(salt: str, value) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]


def name_patterns(names: list[str]) -> list[re.Pattern]:
    """Each full name, and each part of it long enough to be a name rather than a word, longest first."""
    parts: set[str] = set()
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        parts.add(name)
        parts.update(p for p in re.split(r"\s+", name) if len(p) >= MIN_NAME_PART and p not in {"Dr", "Dr.", "د."})
    return [re.compile(rf"(?<!\w){re.escape(p)}(?!\w)", re.IGNORECASE) for p in sorted(parts, key=len, reverse=True)]


def deidentify(value: str | None, names: list[re.Pattern]) -> str | None:
    if value is None:
        return None
    value = EMAIL.sub("[email]", value)
    value = DATE.sub("[date]", value)
    value = NUMBER.sub("[number]", value)
    for pattern in names:
        value = pattern.sub("[name]", value)
    return value


def _deep(value, names):
    """De-identifies every string inside a JSON value (a note, a transcript)."""
    if isinstance(value, str):
        return deidentify(value, names)
    if isinstance(value, list):
        return [_deep(v, names) for v in value]
    if isinstance(value, dict):
        return {k: _deep(v, names) for k, v in value.items()}
    return value


CONSENTED = text("SELECT DISTINCT patient_id FROM identity.consents WHERE kind = 'service_improvement' AND revoked_at IS NULL")
PATIENT_NAMES = text("SELECT id, full_name FROM identity.patients WHERE id = ANY(:ids)")
DOCTOR_NAMES = text("SELECT full_name_en, full_name_ar FROM identity.doctors")

CHAT_RATINGS = text(
    """
    SELECT f.rating, f.patient_id, f.doctor_id, f.created_at, r.content AS reply, r.model, r.prompt_version,
           r.intent, r.safety, q.content AS question
    FROM conversation.reply_feedback f
    JOIN conversation.messages r ON r.id = f.message_id
    LEFT JOIN LATERAL (
        SELECT content FROM conversation.messages p
        WHERE p.conversation_id = r.conversation_id AND p.role = 'patient' AND p.created_at <= r.created_at
        ORDER BY p.created_at DESC LIMIT 1
    ) q ON true
    WHERE f.patient_id = ANY(:ids) AND f.created_at >= :since
    ORDER BY f.created_at
    """
)
ESCALATIONS = text(
    """
    SELECT e.id, e.patient_id, e.doctor_id, e.reason, e.status, e.doctor_reply, e.created_at, e.answered_at,
           m.content AS question
    FROM conversation.escalations e JOIN conversation.messages m ON m.id = e.message_id
    WHERE e.patient_id = ANY(:ids) AND e.created_at >= :since
    ORDER BY e.created_at
    """
)
VISIT_NOTES = text(
    """
    SELECT id, patient_id, doctor_id, transcript, draft, approved, share_with_patient, model, prompt_version,
           started_at, approved_at
    FROM consultation.consultations
    WHERE status = 'approved' AND patient_id = ANY(:ids) AND started_at >= :since
    ORDER BY started_at
    """
)
AUDIT = text(
    "INSERT INTO audit.audit_log (service, actor_type, action, resource_type, detail)"
    " VALUES ('feedback-export', 'system', 'export_feedback', 'dataset', CAST(:detail AS jsonb))"
)

# the questions a gate sent on because it could not decide are the ones worth labelling
UNDECIDED = {"unclear", "output_guard"}


async def export(owner_url: str, out: Path, salt: str, since: datetime) -> dict:
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as db:
            ids = (await db.execute(CONSENTED)).scalars().all()
            patient_names = dict((await db.execute(PATIENT_NAMES, {"ids": ids})).all()) if ids else {}
            doctor_names = [n for row in (await db.execute(DOCTOR_NAMES)).all() for n in row]
            ratings = (await db.execute(CHAT_RATINGS, {"ids": ids, "since": since})).mappings().all() if ids else []
            escalated = (await db.execute(ESCALATIONS, {"ids": ids, "since": since})).mappings().all() if ids else []
            visits = (await db.execute(VISIT_NOTES, {"ids": ids, "since": since})).mappings().all() if ids else []
    finally:
        await engine.dispose()

    doctors = name_patterns(doctor_names)

    def names_for(patient_id) -> list[re.Pattern]:
        # the patient's own name first: their parts may be longer than a doctor's
        return name_patterns([patient_names.get(patient_id, "")]) + doctors

    def who(row) -> dict:
        return {"patient": pseudonym(salt, row["patient_id"]), "doctor": pseudonym(salt, row["doctor_id"])}

    chat_rows, escalation_rows, visit_rows, candidates = [], [], [], []
    for r in ratings:
        names = names_for(r["patient_id"])
        question = deidentify(r["question"], names)
        chat_rows.append(
            {
                **who(r),
                "rating": r["rating"],
                "question": question,
                "reply": deidentify(r["reply"], names),
                "intent": r["intent"],
                "model": r["model"],
                "prompt_version": r["prompt_version"],
                "safety": r["safety"],
                "rated_on": r["created_at"].date().isoformat(),
            }
        )
        if r["rating"] == "down" and question:
            candidates.append({"source": "thumbs_down", "text": question, "expect": None, "lang": None})
    for e in escalated:
        names = names_for(e["patient_id"])
        answered = e["answered_at"]
        escalation_rows.append(
            {
                **who(e),
                "id": pseudonym(salt, e["id"]),
                "reason": e["reason"],
                "status": e["status"],
                "question": deidentify(e["question"], names),
                "doctor_reply": deidentify(e["doctor_reply"], names),
                "hours_to_answer": round((answered - e["created_at"]).total_seconds() / 3600, 1) if answered else None,
            }
        )
        if e["reason"] in UNDECIDED:
            candidates.append(
                {"source": f"escalated_{e['reason']}", "text": deidentify(e["question"], names), "expect": None, "lang": None}
            )
    for v in visits:
        names = names_for(v["patient_id"])
        visit_rows.append(
            {
                **who(v),
                "id": pseudonym(salt, v["id"]),
                "transcript": _deep(v["transcript"], names),
                "draft": _deep(v["draft"], names),
                "approved": _deep(v["approved"], names),
                "edited": v["draft"] != v["approved"],
                "shared_with_patient": v["share_with_patient"],
                "model": v["model"],
                "prompt_version": v["prompt_version"],
            }
        )

    out.mkdir(parents=True, exist_ok=True)
    files = {
        "chat_ratings.jsonl": chat_rows,
        "escalations.jsonl": escalation_rows,
        "visit_notes.jsonl": visit_rows,
        "eval_candidates.jsonl": candidates,
    }
    for name, rows in files.items():
        with (out / name).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    manifest = {
        "exported_at": datetime.now(UTC).isoformat(),
        "since": since.isoformat(),
        "consenting_patients": len(ids),
        "counts": {name: len(rows) for name, rows in files.items()},
        "review_required": True,
        "note": "De-identified by pattern: read every row before it reaches an eval set or a training run.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as db:
            await db.execute(AUDIT, {"detail": json.dumps({"counts": manifest["counts"], "since": manifest["since"]})})
    finally:
        await engine.dispose()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=f"data/feedback/{datetime.now(UTC):%Y-%m-%d}")
    parser.add_argument("--since", default="1970-01-01", help="only feedback from this date (YYYY-MM-DD)")
    args = parser.parse_args()
    salt = os.environ.get("FEEDBACK_SALT", "")
    if len(salt) < 16:
        raise SystemExit("set FEEDBACK_SALT (16+ characters, kept secret and stable) so pseudonyms cannot be reversed")
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    manifest = asyncio.run(export(get_setting().database_owner_url, Path(args.out), salt, since))
    print(json.dumps(manifest["counts"]), "->", args.out)


if __name__ == "__main__":
    main()
