from unittest.mock import AsyncMock, MagicMock, patch

from tests import get_client


def test_chat_completion_returns_llm_response() -> None:
    # GIVEN a chat request and an LLM that answers it
    fake_response = MagicMock()
    fake_response.message.content = "hello there"
    fake_response.message.role.value = "assistant"
    fake_llm = MagicMock()
    fake_llm.achat = AsyncMock(return_value=fake_response)

    # WHEN the completion endpoint is called
    with patch("app.routers.chat.build_llm", return_value=fake_llm):
        client = get_client()
        response = client.post(
            "/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    # THEN the LLM's answer is returned
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "hello there"
    assert body["role"] == "assistant"


def test_chat_completion_surfaces_upstream_error() -> None:
    # GIVEN an LLM call that fails upstream
    import openai

    fake_llm = MagicMock()
    fake_llm.achat = AsyncMock(side_effect=openai.OpenAIError("boom"))

    # WHEN the completion endpoint is called
    with patch("app.routers.chat.build_llm", return_value=fake_llm):
        client = get_client()
        response = client.post(
            "/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    # THEN the error is surfaced as a 500 with the upstream detail
    assert response.status_code == 500
    assert "boom" in response.json()["detail"]
