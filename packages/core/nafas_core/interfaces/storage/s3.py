import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from nafas_core.exceptions.providers import StorageError


class S3Storage:
    """Any S3-compatible store: SeaweedFS locally, AWS S3 or similar in production."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        public_endpoint_url: str | None = None,
    ):
        self.bucket = bucket
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url or None
        # links are handed to browsers, which may reach the store by another name than
        # the services do (s3:8333 inside compose); a link is signed for its host, so it
        # is made against that name rather than rewritten afterwards
        self._public_endpoint_url = public_endpoint_url or self._endpoint_url

    def _client(self, endpoint_url: str | None = None):
        return self._session.client("s3", endpoint_url=endpoint_url or self._endpoint_url)

    async def ensure_bucket(self) -> None:
        """Creates the bucket if it is missing; for local setup, not the request path."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self.bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as s3:
                await s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"could not store {key}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        try:
            async with self._client() as s3:
                response = await s3.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as body:
                    return await body.read()
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"could not read {key}: {exc}") from exc

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"could not delete {key}: {exc}") from exc

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str:
        async with self._client(self._public_endpoint_url) as s3:
            return await s3.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds
            )

    async def presigned_put_url(self, key: str, content_type: str, expires_seconds: int = 300) -> str:
        async with self._client(self._public_endpoint_url) as s3:
            return await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_seconds,
            )
