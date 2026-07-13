import os

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/evalhub_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _dispose_engine():
    yield
    from app.db import engine

    engine.dispose()


@pytest.fixture(autouse=True)
def _db():
    from app.db import Base, engine
    import app.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def object_store(monkeypatch):
    from app import storage

    objects = {}
    monkeypatch.setattr(storage, "put_object", objects.__setitem__)
    monkeypatch.setattr(storage, "get_object", objects.__getitem__)
    monkeypatch.setattr(storage, "delete_object", objects.__delitem__)
    return objects
