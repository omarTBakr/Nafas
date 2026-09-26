"""
The clinical-records activities: reading a document, describing an image,
indexing it. Each is idempotent (a retry redoes the same step to the same
result), so every one of them may be retried.
"""

import base64
import hashlib
import uuid

from temporalio import activity

from nafas_clinical.enums import DocumentStatus, SourceType
from nafas_clinical.logic import records, search
from nafas_clinical.logic.extraction import IMAGE_TYPES, extract
from nafas_clinical.prompts import vision
from nafas_clinical.schemas import DocumentRef, Failure, ReadResult
from nafas_core.db import session_scope
from nafas_core.interfaces.embeddings import Embeddings
from nafas_core.interfaces.llm import LLM
from nafas_core.interfaces.storage.base import Storage
from nafas_core.metrics import WORKFLOW_FAILURES

# Claude reads these image types directly; others are described from their OCR text only
VISION_TYPES = {"image/png", "image/jpeg", "image/webp"}


class ClinicalActivities:
    def __init__(self, storage: Storage, embeddings: Embeddings, llm: LLM | None, vision_model: str):
        self._storage = storage
        self._embeddings = embeddings
        self._llm = llm
        self._vision_model = vision_model

    @activity.defn(name="clinical.read_document")
    async def read_document(self, ref: DocumentRef) -> ReadResult:
        doctor_id, document_id = uuid.UUID(ref.doctor_id), uuid.UUID(ref.document_id)
        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.get_document(session, document_id)
            key, mime = document.object_key, document.mime
            await records.mark(session, document_id, DocumentStatus.PROCESSING)

        data = await self._storage.get(key)
        extracted = await extract(data, mime)

        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.get_document(session, document_id)
            document.sha256 = hashlib.sha256(data).hexdigest()
            document.size_bytes = len(data)
            document.page_count = extracted.page_count
            document.extracted_text = extracted.text
        return ReadResult(is_image=mime in IMAGE_TYPES, characters=len(extracted.text), page_count=extracted.page_count)

    @activity.defn(name="clinical.describe_image")
    async def describe_image(self, ref: DocumentRef) -> str | None:
        """A model's description for search, labelled as such; never a clinical read."""
        doctor_id, document_id = uuid.UUID(ref.doctor_id), uuid.UUID(ref.document_id)
        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.get_document(session, document_id)
            key, mime = document.object_key, document.mime
        if self._llm is None or mime not in VISION_TYPES:
            return None

        image = base64.b64encode(await self._storage.get(key)).decode()
        response = await self._llm.create(
            model=self._vision_model,
            system=vision.SYSTEM,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image}},
                        {"type": "text", "text": "Describe this image as instructed."},
                    ],
                }
            ],
        )
        description = "".join(b.text for b in response.content if b.type == "text").strip()
        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.get_document(session, document_id)
            document.ai_description = description or None
        return description or None

    @activity.defn(name="clinical.index_document")
    async def index_document(self, ref: DocumentRef) -> int:
        doctor_id, document_id = uuid.UUID(ref.doctor_id), uuid.UUID(ref.document_id)
        async with session_scope(doctor_id=doctor_id) as session:
            document = await records.get_document(session, document_id)
            text = document.extracted_text or ""
            if document.ai_description:
                text += f"\n\n[{vision.LABEL}] {document.ai_description}"
            count = await search.index(
                session,
                self._embeddings,
                patient_id=document.patient_id,
                doctor_id=document.doctor_id,
                source_type=SourceType.DOCUMENT,
                source_id=document.id,
                text=text,
                visibility=document.visibility,
                details={"filename": document.filename, "kind": document.kind.value, "document_id": str(document.id)},
            )
            await records.mark(session, document_id, DocumentStatus.INDEXED)
        return count

    @activity.defn(name="clinical.mark_failed")
    async def mark_failed(self, failure: Failure) -> None:
        async with session_scope(doctor_id=uuid.UUID(failure.doctor_id)) as session:
            await records.mark(session, uuid.UUID(failure.document_id), DocumentStatus.FAILED, failure.error[:500])
        WORKFLOW_FAILURES.labels("document_ingestion").inc()

    def all(self) -> list:
        return [self.read_document, self.describe_image, self.index_document, self.mark_failed]
