from nafas_core.config import get_setting
from nafas_core.enums.providers import StorageProvider
from nafas_core.interfaces.storage.base import Storage

_storage: Storage | None = None


def get_storage() -> Storage:
    """The process-wide storage for STORAGE_PROVIDER."""
    global _storage
    if _storage is None:
        settings = get_setting()
        match settings.storage_provider:
            case StorageProvider.S3:
                from nafas_core.interfaces.storage.s3 import S3Storage

                _storage = S3Storage(
                    bucket=settings.s3_bucket,
                    endpoint_url=settings.s3_endpoint_url,
                    region=settings.s3_region,
                    access_key=settings.s3_access_key.get_secret_value(),
                    secret_key=settings.s3_secret_key.get_secret_value(),
                )

    return _storage


def set_storage(storage: Storage | None) -> None:
    """Replaces the process-wide storage; tests pass an InMemoryStorage, and None to reset."""
    global _storage
    _storage = storage
