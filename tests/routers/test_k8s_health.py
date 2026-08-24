from tests import get_client


def test_healthz() -> None:
    client = get_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz() -> None:
    client = get_client()

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
