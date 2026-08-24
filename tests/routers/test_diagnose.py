from unittest.mock import AsyncMock, patch

from app.agents.hitl import approval_store
from app.core.config import settings
from app.persistence.store import store
from tests import get_client


def teardown_function() -> None:
    store._investigations.clear()
    approval_store._pending.clear()


def test_list_diagnoses_returns_newest_first() -> None:
    client = get_client()
    older = store.create(namespace="staging")
    newer = store.create(namespace="test")

    response = client.get("/diagnose")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()]
    assert ids == [newer.id, older.id]


def test_start_diagnosis_rejects_namespace_outside_allowlist(
    monkeypatch,
) -> None:
    # GIVEN a namespace that is not allowlisted
    monkeypatch.setattr(settings, "kube_allowed_namespaces", ["staging"])
    client = get_client()

    # WHEN an investigation is requested for it
    response = client.post("/diagnose", json={"namespace": "prod"})

    # THEN the request is refused
    assert response.status_code == 403


def test_start_diagnosis_schedules_investigation(monkeypatch) -> None:
    # GIVEN an allowlisted namespace
    monkeypatch.setattr(settings, "kube_allowed_namespaces", ["staging"])
    client = get_client()

    # WHEN an investigation is requested
    with patch(
        "app.routers.diagnose.run_investigation", new=AsyncMock()
    ) as mocked:
        response = client.post("/diagnose", json={"namespace": "staging"})

    # THEN it is accepted, persisted, and the background task is scheduled
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    investigation = store.get(body["id"])
    assert investigation is not None
    assert investigation.namespace == "staging"
    mocked.assert_called_once()


def test_get_diagnosis_returns_404_for_unknown_id() -> None:
    client = get_client()

    response = client.get("/diagnose/does-not-exist")

    assert response.status_code == 404


async def test_get_diagnosis_includes_pending_approval() -> None:
    # GIVEN an investigation with a pending write-tool approval
    client = get_client()
    investigation = store.create(namespace="staging")
    approval_store.request(
        investigation.id, "restart_deployment", {"deployment": "web"}
    )

    # WHEN its detail is fetched
    response = client.get(f"/diagnose/{investigation.id}")

    # THEN the pending approval is visible
    assert response.status_code == 200
    body = response.json()
    assert body["pending_approval"]["tool_name"] == "restart_deployment"


def test_decide_returns_404_for_unknown_investigation() -> None:
    client = get_client()

    response = client.post(
        "/diagnose/does-not-exist/decisions", json={"decision": "approve"}
    )

    assert response.status_code == 404


def test_decide_returns_409_when_nothing_pending() -> None:
    client = get_client()
    investigation = store.create(namespace="staging")

    response = client.post(
        f"/diagnose/{investigation.id}/decisions", json={"decision": "approve"}
    )

    assert response.status_code == 409


async def test_decide_resolves_pending_approval() -> None:
    # GIVEN a pending approval
    client = get_client()
    investigation = store.create(namespace="staging")
    approval_store.request(
        investigation.id, "restart_deployment", {"deployment": "web"}
    )

    # WHEN the operator approves it
    response = client.post(
        f"/diagnose/{investigation.id}/decisions",
        json={"decision": "approve", "reason": "looks safe"},
    )

    # THEN the decision is recorded and nothing is left pending
    assert response.status_code == 204
    assert approval_store.get(investigation.id) is None
