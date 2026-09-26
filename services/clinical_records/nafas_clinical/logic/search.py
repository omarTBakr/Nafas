"""
Indexing a record into passages, and finding the passages that answer a question.

Search is hybrid: nearest embeddings (meaning, across Arabic and English)
and full-text matches (exact names, drugs, numbers), fused by reciprocal
rank. It runs in the caller's scope, so row-level security decides what can
come back at all: a patient's scope finds only what their doctor shared.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_clinical.enums import SourceType, Visibility
from nafas_clinical.logic.chunking import split_text
from nafas_clinical.models import Chunk
from nafas_core.interfaces.embeddings import Embeddings
from nafas_core.tracing import step

# each method proposes this many times k before fusing; RRF's usual constant
CANDIDATES = 4
RRF_K = 60


@dataclass
class Passage:
    chunk_id: uuid.UUID
    source_type: SourceType
    source_id: uuid.UUID
    content: str
    visibility: Visibility
    details: dict
    score: float


async def index(
    session: AsyncSession,
    embeddings: Embeddings,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    source_type: SourceType,
    source_id: uuid.UUID,
    text: str,
    visibility: Visibility,
    details: dict | None = None,
) -> int:
    """Replaces the source's passages with fresh ones; how many there are now."""
    await session.execute(delete(Chunk).where(Chunk.source_type == source_type, Chunk.source_id == source_id))
    passages = split_text(text)
    if not passages:
        return 0
    vectors = await embeddings.embed(passages)
    for position, (content, vector) in enumerate(zip(passages, vectors, strict=True)):
        session.add(
            Chunk(
                patient_id=patient_id,
                doctor_id=doctor_id,
                source_type=source_type,
                source_id=source_id,
                position=position,
                content=content,
                embedding=vector,
                visibility=visibility,
                details=details or {},
            )
        )
    await session.flush()
    return len(passages)


@step("clinical.search", run_type="retriever")
async def search(
    session: AsyncSession, embeddings: Embeddings, *, patient_id: uuid.UUID, doctor_id: uuid.UUID, query: str, k: int = 6
) -> list[Passage]:
    """The k passages of this patient's record with this doctor that best answer `query`."""
    [vector] = await embeddings.embed([query])
    mine = (Chunk.patient_id == patient_id, Chunk.doctor_id == doctor_id)

    by_meaning = (
        (
            await session.execute(
                select(Chunk.id).where(*mine).order_by(Chunk.embedding.cosine_distance(vector)).limit(k * CANDIDATES)
            )
        )
        .scalars()
        .all()
    )
    words = func.plainto_tsquery("simple", query)
    by_words = (
        (
            await session.execute(
                select(Chunk.id)
                .where(*mine, Chunk.tsv.op("@@")(words))
                .order_by(func.ts_rank(Chunk.tsv, words).desc())
                .limit(k * CANDIDATES)
            )
        )
        .scalars()
        .all()
    )

    scores: dict[uuid.UUID, float] = {}
    for ranking in (by_meaning, by_words):
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    best = sorted(scores, key=scores.get, reverse=True)[:k]
    if not best:
        return []
    chunks = {c.id: c for c in (await session.scalars(select(Chunk).where(Chunk.id.in_(best)))).all()}
    return [
        Passage(c.id, c.source_type, c.source_id, c.content, c.visibility, c.details, scores[c.id])
        for c in (chunks[i] for i in best)
    ]
