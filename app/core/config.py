import os
from typing import Annotated

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode

load_dotenv()


def _split_namespaces(raw: str) -> list[str]:
    return [ns.strip() for ns in raw.split(",") if ns.strip()]


class Settings(BaseSettings):
    litellm_base_url: str = os.getenv("LITELLM_API_BASE", "litellm-base-url")
    litellm_api_key: str = os.getenv("LITELLM_API_KEY", "your-litellm-api-key")
    litellm_model: str = os.getenv(
        "LITELLM_API_MODEL", "desired-llm-model-from-litellm"
    )
    llm_max_tokens: int = int(os.getenv("LITELLM_MAX_TOKENS", "4096"))

    # Fail closed: an empty allowlist means no namespace is reachable.
    # NoDecode: pydantic-settings otherwise JSON-decodes env values for
    # list-typed fields, which crashes on a plain comma-separated string
    # like "default,staging" — the validator below does the real parsing.
    kube_allowed_namespaces: Annotated[list[str], NoDecode] = (
        _split_namespaces(os.getenv("KUBE_ALLOWED_NAMESPACES", ""))
    )
    kube_max_hops: int = int(os.getenv("KUBE_MAX_HOPS", "8"))
    approval_timeout_seconds: int = int(
        os.getenv("APPROVAL_TIMEOUT_SECONDS", "600")
    )

    @field_validator("kube_allowed_namespaces", mode="before")
    @classmethod
    def _parse_allowed_namespaces(cls, value: str | list[str]) -> list[str]:
        return _split_namespaces(value) if isinstance(value, str) else value


settings = Settings()
