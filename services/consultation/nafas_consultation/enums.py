from enum import StrEnum


class ConsultationStatus(StrEnum):
    # consent taken, parts being uploaded from the browser
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    # waiting for the doctor to read, edit and approve (or discard)
    DRAFT_READY = "draft_ready"
    # approved; the workflow is writing it to the record
    FILING = "filing"
    APPROVED = "approved"
    DISCARDED = "discarded"
    FAILED = "failed"


# the doctor may throw a recording away at any point before it is filed
DISCARDABLE = {
    ConsultationStatus.RECORDING,
    ConsultationStatus.TRANSCRIBING,
    ConsultationStatus.SUMMARIZING,
    ConsultationStatus.DRAFT_READY,
    ConsultationStatus.FAILED,
}
