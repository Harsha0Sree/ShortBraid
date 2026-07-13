from minio import Minio

from app.core.config import settings

client = Minio(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
)

if client.bucket_exists(settings.bucket_name) is False:
    client.make_bucket(settings.bucket_name)

