from typing import Any

from llama_index.llms.openai_like import OpenAILike
from pydantic import Field

from app.core.config import settings


class KubeAgentLlm(OpenAILike):
    """OpenAILike variant that optionally drops `temperature` from requests.

    Newer Claude models on Bedrock reject `temperature` as an unsupported
    parameter, so it is stripped by default.
    """

    enable_temperature: bool = Field(
        default=False,
        description=(
            "If True, forward `temperature` to the upstream model. "
            "Defaults to False for compatibility with newer Claude models "
            "that reject `temperature`."
        ),
    )

    def _get_model_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        base_kwargs = super()._get_model_kwargs(**kwargs)
        if not self.enable_temperature:
            base_kwargs.pop("temperature", None)
        return base_kwargs


def build_llm(enable_temperature: bool = False) -> KubeAgentLlm:
    """Build a KubeAgentLlm configured from environment settings.

    Shared factory so every entry point (REST router, background
    investigation runner) stays in sync on LLM instantiation.
    """
    return KubeAgentLlm(
        api_base=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
        model=settings.litellm_model,
        is_chat_model=True,
        is_function_calling_model=True,
        max_tokens=settings.llm_max_tokens,
        context_window=200_000,
        enable_temperature=enable_temperature,
    )
