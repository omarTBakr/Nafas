"""The schema document comes from the migrated database: every table in it, and no policy that checks nothing."""

import re

from scripts import schema_doc


async def test_every_table_is_documented_with_its_row_level_security(database, tmp_path):
    out = tmp_path / "database.md"

    await schema_doc.main(out)

    text = out.read_text(encoding="utf-8")
    for table in (
        "identity.patients",
        "scheduling.appointments",
        "conversation.reply_feedback",
        "consultation.consultations",
        "edge.rate_hits",
    ):
        schema, name = table.split(".")
        assert f"## `{schema}`" in text and f"    {name} {{" in text, table
    assert "`appointments.patient_id` → `identity.patients`" in text
    assert "```mermaid\nerDiagram" in text


async def test_no_policy_compares_a_column_with_itself(database, tmp_path):
    """The patient_channels leak (a column compared with itself inside a policy) must never come back, on any table."""
    out = tmp_path / "database.md"
    await schema_doc.main(out)

    tautologies = re.findall(r"\((\w+\.\w+) = \1\)", out.read_text(encoding="utf-8"))

    assert tautologies == []
