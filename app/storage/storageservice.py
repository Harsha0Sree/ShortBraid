from uuid import uuid4


class StorageService:
    def __init__(self, client, bucket_name):
        self.client = client
        self.bucket_name = bucket_name

    def upload_document(self, data: bytes, file_name: str, content_type: str):
        object_name = str(uuid4())
        self.client.put_object(
            bucket_name=self.bucket_name,
            object_name=object_name,
            data=data,
            content_type=content_type,
        )
        return {"object_name": object_name, "bucket_name": self.bucket_name}
