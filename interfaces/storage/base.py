from typing import Protocol
from uuid import UUID


def patient_key(doctor_id: UUID, patient_id: UUID, *parts: str) -> str:
    """The object key for a file belonging to one patient of one doctor."""
    return "/".join(["doctor", str(doctor_id), "patient", str(patient_id), *parts])


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes:
        """Raises StorageError when the key does not exist."""
        ...

    async def delete(self, key: str) -> None: ...

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str: ...

    async def presigned_put_url(self, key: str, content_type: str, expires_seconds: int = 300) -> str:
        """A URL a browser can PUT one file to directly, bypassing the API."""
        ...
