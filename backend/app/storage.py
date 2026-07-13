from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from app.config import settings


@lru_cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        region_name=settings.aws_region,
    )


def _ensure_bucket(client) -> None:
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
            raise
        kwargs = {"Bucket": settings.s3_bucket}
        if settings.aws_region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": settings.aws_region
            }
        client.create_bucket(**kwargs)


def put_object(key: str, data: bytes) -> None:
    client = _client()
    _ensure_bucket(client)
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data)


def get_object(key: str) -> bytes:
    response = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return response["Body"].read()


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=settings.s3_bucket, Key=key)
