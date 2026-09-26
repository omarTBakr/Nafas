"""The clinical-records workflows. They decide order and never do I/O."""

from nafas_clinical.workflows.ingestion import DocumentIngestionWorkflow

WORKFLOWS = [DocumentIngestionWorkflow]

__all__ = ["WORKFLOWS", "DocumentIngestionWorkflow"]
