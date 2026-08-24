import openai
from fastapi import APIRouter, HTTPException, status
from llama_index.core.llms import ChatMessage, MessageRole

from app.core.llm import build_llm
from app.dependencies import settings_dependency
from app.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    path="/completions",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_200_OK,
)
async def chat_completion(
    request: ChatCompletionRequest,
    settings: settings_dependency,
) -> ChatCompletionResponse:
    try:
        llm = build_llm(enable_temperature=request.enable_temperature)

        messages = [
            ChatMessage(
                role=MessageRole(msg.role.lower()), content=msg.content
            )
            for msg in request.messages
        ]

        response = await llm.achat(messages)

        return ChatCompletionResponse(
            model=settings.litellm_model,
            content=response.message.content or "",
            role=response.message.role.value,
        )
    except openai.OpenAIError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating completion: {e!s}",
        ) from e
