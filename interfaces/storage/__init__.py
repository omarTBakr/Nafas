"""The object storage port: voice notes, recordings, reports and scans.

Keys are laid out `doctor/{doctor_id}/patient/{patient_id}/...` so a whole
patient can be listed, exported or erased by prefix. Files reach browsers
through short-lived presigned URLs, never through the API process.
"""

from interfaces.storage.base import Storage, patient_key
from interfaces.storage.factory import get_storage

__all__ = ["Storage", "get_storage", "patient_key"]
