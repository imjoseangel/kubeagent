from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from kubernetes.client.exceptions import ApiException

from app.core.dependency_checks import check_kube_api, check_llm


async def test_check_kube_api_ok_when_version_returns() -> None:
    version_api = MagicMock()
    version_api.get_code.return_value = MagicMock(git_version="v1.29.0")

    with patch(
        "app.core.dependency_checks.client.version_api",
        return_value=version_api,
    ):
        result = await check_kube_api()

    assert result.name == "kube_api"
    assert result.ok is True
    assert result.status_code == 200
    assert "v1.29.0" in result.message


async def test_check_kube_api_fails_on_api_exception() -> None:
    with patch(
        "app.core.dependency_checks.client.version_api",
        side_effect=ApiException(status=401, reason="Unauthorized"),
    ):
        result = await check_kube_api()

    assert result.name == "kube_api"
    assert result.ok is False
    assert result.status_code == 401
    assert "Unauthorized" in result.message


async def test_check_kube_api_fails_on_connection_error() -> None:
    with patch(
        "app.core.dependency_checks.client.version_api",
        side_effect=OSError("connection refused"),
    ):
        result = await check_kube_api()

    assert result.ok is False
    assert result.status_code == 503


async def test_check_llm_ok_when_endpoint_responds() -> None:
    response = MagicMock(status_code=200)
    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check_llm()

    assert result.name == "llm"
    assert result.ok is True
    assert result.status_code == 200


async def test_check_llm_fails_on_connection_error() -> None:
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("connection refused")
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check_llm()

    assert result.name == "llm"
    assert result.ok is False
    assert result.status_code == 503
