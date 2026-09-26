"""Dataclasses crossing a Temporal boundary. New fields need defaults."""

from dataclasses import dataclass

INGESTION_WORKFLOW = "DocumentIngestionWorkflow"


def ingestion_workflow_id(document_id: str) -> str:
    return f"ingest-{document_id}"


@dataclass
class DocumentRef:
    document_id: str
    doctor_id: str


@dataclass
class ReadResult:
    is_image: bool
    characters: int
    page_count: int | None = None


@dataclass
class Failure:
    document_id: str
    doctor_id: str
    error: str
