from io import BytesIO


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.bucket_exists = False

    def head_bucket(self, Bucket):
        if not self.bucket_exists:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, **kwargs):
        self.bucket_exists = True

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key)


def test_object_roundtrip(monkeypatch):
    from app import storage

    fake = FakeS3()
    monkeypatch.setattr(storage, "_client", lambda: fake)

    storage.put_object("datasets/ws/data.csv", b"a,b\n1,2\n")
    assert fake.bucket_exists
    assert storage.get_object("datasets/ws/data.csv") == b"a,b\n1,2\n"
    storage.delete_object("datasets/ws/data.csv")
    assert fake.objects == {}
