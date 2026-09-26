"""The scheduling service's workflows. They decide order and never do I/O."""

from nafas_scheduling.workflows.booking import BookingWorkflow

WORKFLOWS = [BookingWorkflow]

__all__ = ["WORKFLOWS", "BookingWorkflow"]
