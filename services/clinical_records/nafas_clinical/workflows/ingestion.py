"""
DocumentIngestionWorkflow: an uploaded file becomes searchable.

Read it (PDF text, OCR for scanned pages and images), describe it if it is
an image, then chunk and embed it. A step that keeps failing marks the
document failed with the reason, which the doctor sees; nothing is indexed
half-way, because indexing replaces the document's passages in one go.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from nafas_clinical.activities import ClinicalActivities
    from nafas_clinical.schemas import INGESTION_WORKFLOW, DocumentRef, Failure

READ = {"start_to_close_timeout": timedelta(minutes=10), "retry_policy": RetryPolicy(maximum_attempts=3)}
DESCRIBE = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": RetryPolicy(maximum_attempts=2)}
INDEX = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": RetryPolicy(maximum_attempts=5)}
MARK = {"start_to_close_timeout": timedelta(seconds=30), "retry_policy": RetryPolicy(maximum_attempts=10)}


@workflow.defn(name=INGESTION_WORKFLOW)
class DocumentIngestionWorkflow:
    @workflow.run
    async def run(self, ref: DocumentRef) -> str:
        try:
            read = await workflow.execute_activity_method(ClinicalActivities.read_document, ref, **READ)
            if read.is_image:
                try:
                    await workflow.execute_activity_method(ClinicalActivities.describe_image, ref, **DESCRIBE)
                except ActivityError:
                    # the OCR text still makes it searchable; the description is extra
                    workflow.logger.warning("image description failed; indexing the text alone")
            await workflow.execute_activity_method(ClinicalActivities.index_document, ref, **INDEX)
        except ActivityError as failed:
            cause = failed.cause.message if failed.cause else str(failed)
            await workflow.execute_activity_method(
                ClinicalActivities.mark_failed, Failure(ref.document_id, ref.doctor_id, cause), **MARK
            )
            return "failed"
        return "indexed"
