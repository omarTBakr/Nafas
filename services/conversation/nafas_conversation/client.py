"""Sending a patient's message: the contract lives in nafas_core, shared with the gateway."""

from nafas_core.clients.conversation import send_patient_message

__all__ = ["send_patient_message"]
