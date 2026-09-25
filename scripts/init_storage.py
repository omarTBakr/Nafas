"""Creates the S3 bucket named by S3_BUCKET if it does not exist: `uv run python -m scripts.init_storage`."""

import asyncio

from interfaces.storage.s3 import S3Storage
from utils.config import get_setting


async def main() -> None:
    settings = get_setting()
    storage = S3Storage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
    )
    await storage.ensure_bucket()
    print(f"bucket {settings.s3_bucket!r} ready at {settings.s3_endpoint_url}")


if __name__ == "__main__":
    asyncio.run(main())
