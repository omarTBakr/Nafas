"""
Writes docs/architecture/database.md from a migrated database, so the
schema documentation cannot drift from the schema:
`uv run python -m scripts.schema_doc` (reads DATABASE_OWNER_URL).

For each service's schema: an entity-relationship diagram (Mermaid, which
GitHub renders), every column with its type, and the row-level security
policies that decide who sees a row. Foreign keys across schemas (into
identity) are listed on their own: they live in the database, never on
another service's models.
"""

import argparse
import asyncio
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_core.config import get_setting

SCHEMAS = {
    "identity": "identity service: accounts, doctors, patients, care links, consents",
    "scheduling": "scheduling service: hours, time off, appointments, notices",
    "conversation": "conversation service: the patient's chat, escalations, reply ratings",
    "clinical": "clinical-records service: history, documents and their searchable passages",
    "consultation": "consultation service: recorded visits",
    "edge": "gateway: rate limits shared by its replicas",
    "audit": "every service appends; no service reads",
}

COLUMNS = text("""
    SELECT c.table_schema, c.table_name, c.column_name,
           CASE WHEN c.data_type = 'USER-DEFINED' THEN c.udt_name ELSE c.data_type END AS type,
           c.is_nullable = 'YES' AS nullable
    FROM information_schema.columns c
    WHERE c.table_schema = ANY(:schemas)
    ORDER BY c.table_schema, c.table_name, c.ordinal_position
    """)
KEYS = text("""
    SELECT n.nspname, t.relname, a.attname
    FROM pg_constraint k
    JOIN pg_class t ON t.oid = k.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(k.conkey)
    WHERE k.contype = 'p' AND n.nspname = ANY(:schemas)
    """)
FOREIGN = text("""
    SELECT n.nspname, t.relname, a.attname, fn.nspname, ft.relname
    FROM pg_constraint k
    JOIN pg_class t ON t.oid = k.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_class ft ON ft.oid = k.confrelid JOIN pg_namespace fn ON fn.oid = ft.relnamespace
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.conkey[1]
    WHERE k.contype = 'f' AND n.nspname = ANY(:schemas)
    ORDER BY 1, 2, 3
    """)
POLICIES = text("""
    SELECT schemaname, tablename, policyname, cmd, qual, with_check
    FROM pg_policies WHERE schemaname = ANY(:schemas) ORDER BY 1, 2, 3
    """)
SECURED = text("""
    SELECT n.nspname, c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r' AND n.nspname = ANY(:schemas)
    """)


def _mermaid_type(sql_type: str) -> str:
    """Mermaid wants one word for a type."""
    return sql_type.replace("timestamp with time zone", "timestamptz").replace("character varying", "varchar").replace(" ", "_")


def render(columns, keys, foreign, policies, secured) -> str:
    tables: dict[tuple[str, str], list] = defaultdict(list)
    for schema, table, column, sql_type, nullable in columns:
        tables[(schema, table)].append((column, sql_type, nullable))
    primary = {(s, t, c) for s, t, c in keys}
    references = {(s, t, c): (fs, ft) for s, t, c, fs, ft in foreign}
    by_table = defaultdict(list)
    for schema, table, name, command, using, check in policies:
        by_table[(schema, table)].append((name, command, using, check))
    rls = {(s, t): on for s, t, on in secured}

    out = [
        "# Database schema",
        "",
        "Generated from a migrated database by `scripts/schema_doc.py`; do not edit by hand.",
        "Run `uv run python -m scripts.schema_doc` after a migration.",
        "",
        "One Postgres database, one schema per service. A service logs in with a role that holds",
        "its own schema and nothing else (`deploy/postgres/roles.sql`); row-level security then",
        "narrows every row to the doctor or patient the request is for (`nafas_core.db.session_scope`).",
        "",
    ]
    for schema, purpose in SCHEMAS.items():
        names = sorted(t for s, t in tables if s == schema)
        if not names:
            continue
        out += [f"## `{schema}`", "", f"The {purpose}.", "", "```mermaid", "erDiagram"]
        for table in names:
            out.append(f"    {table} {{")
            for column, sql_type, _ in tables[(schema, table)]:
                marks = []
                if (schema, table, column) in primary:
                    marks.append("PK")
                if (schema, table, column) in references:
                    marks.append("FK")
                mark = f" {','.join(marks)}" if marks else ""
                out.append(f"        {_mermaid_type(sql_type)} {column}{mark}")
            out.append("    }")
        for (s, t, column), (fs, ft) in sorted(references.items()):
            if s == schema and fs == schema:
                out.append(f'    {ft} ||--o{{ {t} : "{column}"')
        out += ["```", ""]
        crossing = [(t, c, fs, ft) for (s, t, c), (fs, ft) in sorted(references.items()) if s == schema and fs != schema]
        if crossing:
            out += ["References into other schemas (in the database only, never on the ORM models):", ""]
            out += [f"- `{t}.{c}` → `{fs}.{ft}`" for t, c, fs, ft in crossing]
            out.append("")
        out += ["| Table | Row-level security |", "| --- | --- |"]
        for table in names:
            rules = by_table.get((schema, table), [])
            if not rls.get((schema, table)):
                described = "off (see the isolation sweep for why this table may be open)"
            elif not rules:
                described = "on, no policy: nobody reads it through the app role"
            else:
                described = "<br>".join(
                    f"`{name}` ({command.lower()}): `{' '.join((using or check or '').split())}`"
                    for name, command, using, check in rules
                )
            out.append(f"| `{table}` | {described} |")
        out.append("")
    return "\n".join(out)


async def main(out: Path) -> None:
    engine = create_async_engine(get_setting().database_owner_url)
    params = {"schemas": list(SCHEMAS)}
    try:
        async with engine.connect() as db:
            columns = (await db.execute(COLUMNS, params)).all()
            keys = (await db.execute(KEYS, params)).all()
            foreign = (await db.execute(FOREIGN, params)).all()
            policies = (await db.execute(POLICIES, params)).all()
            secured = (await db.execute(SECURED, params)).all()
    finally:
        await engine.dispose()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(columns, keys, foreign, policies, secured), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path("docs/architecture/database.md"))
    asyncio.run(main(parser.parse_args().out))
