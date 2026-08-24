import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

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
    kube_allowed_namespaces: list[str] = _split_namespaces(
        os.getenv("KUBE_ALLOWED_NAMESPACES", "")
    )
    kube_max_hops: int = int(os.getenv("KUBE_MAX_HOPS", "8"))
    approval_timeout_seconds: int = int(
        os.getenv("APPROVAL_TIMEOUT_SECONDS", "600")
    )


settings = Settings()
