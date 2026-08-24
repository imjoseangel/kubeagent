from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, settings


def get_settings() -> Settings:
    """Get application settings."""
    return settings


settings_dependency = Annotated[Settings, Depends(get_settings)]
