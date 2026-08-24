from tests import get_client


def test_root_returns_service_message() -> None:
    client = get_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "kubeagent - Kubernetes troubleshooting agent"
    }
