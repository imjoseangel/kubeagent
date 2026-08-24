import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.dependency_checks import check_kubectl, check_llm


async def test_check_kubectl_ok_when_command_succeeds() -> None:
    completed = subprocess.CompletedProcess(
        args=["kubectl"], returncode=0, stdout="", stderr=""
    )
    with patch("subprocess.run", return_value=completed):
        result = await check_kubectl()

    assert result.name == "kubectl"
    assert result.ok is True
    assert result.status_code == 200


async def test_check_kubectl_fails_on_non_zero_exit() -> None:
    completed = subprocess.CompletedProcess(
        args=["kubectl"], returncode=1, stdout="", stderr="Unauthorized"
    )
    with patch("subprocess.run", return_value=completed):
        result = await check_kubectl()

    assert result.name == "kubectl"
    assert result.ok is False
    assert result.status_code == 503
    assert "Unauthorized" in result.message


async def test_check_kubectl_fails_when_binary_missing() -> None:
    with patch("subprocess.run", side_effect=OSError("kubectl not found")):
        result = await check_kubectl()

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
