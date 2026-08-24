from fastapi.testclient import TestClient

from app.main import app


def get_client() -> TestClient:
    return TestClient(app)
