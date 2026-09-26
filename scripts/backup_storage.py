"""
Copies every object in the bucket to a directory, or back:
`uv run python -m scripts.backup_storage save DIR` / `... restore DIR`.
Part of `make backup`, which also dumps the database (scripts/backup.sh).
Keys map to paths as they are, so a restore puts each object back where the
database expects it.
"""

import argparse
import asyncio
from pathlib import Path

import aioboto3

from nafas_core.config import get_setting


def _client():
    settings = get_setting()
    session = aioboto3.Session(
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    )
    return session.client("s3", endpoint_url=settings.s3_endpoint_url or None), settings.s3_bucket


async def save(target: Path) -> int:
    client, bucket = _client()
    count = 0
    async with client as s3:
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                path = target / item["Key"]
                path.parent.mkdir(parents=True, exist_ok=True)
                response = await s3.get_object(Bucket=bucket, Key=item["Key"])
                async with response["Body"] as body:
                    path.write_bytes(await body.read())
                count += 1
    return count


async def restore(source: Path) -> int:
    client, bucket = _client()
    count = 0
    async with client as s3:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            await s3.put_object(Bucket=bucket, Key=path.relative_to(source).as_posix(), Body=path.read_bytes())
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["save", "restore"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    count = asyncio.run(save(args.directory) if args.action == "save" else restore(args.directory))
    print(f"{args.action}: {count} objects ({args.directory})")


if __name__ == "__main__":
    main()
