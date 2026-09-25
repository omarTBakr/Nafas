from enum import StrEnum


class TaskQueue(StrEnum):
    """
    One queue per service that runs a worker (docs/PLAN.md §4).

    A queue belongs to exactly one service, and only that service's worker
    polls it — so a deploy of one service can never have another service's
    older code decoding its payloads.
    """

    CHANNELS = "channels"
    IDENTITY = "identity"
    SCHEDULING = "scheduling"
    CONVERSATION = "conversation"
    CLINICAL = "clinical"
    CONSULTATION = "consultation"
