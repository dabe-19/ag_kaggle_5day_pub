import sys
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = None if any("pytest" in arg for arg in sys.argv) else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file, env_file_encoding="utf-8", extra="ignore"
    )

    PORT: int = 8000
    HOST: str = "0.0.0.0"
    LOG_LEVEL: str = "INFO"
    DOCS_USERNAME: str = "admin"
    DOCS_PASSWORD: str = "admin"
    TWITCH_CLIENT_ID: Optional[str] = None
    TWITCH_CLIENT_SECRET: Optional[str] = None
    YOUTUBE_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    DISABLE_INTERNAL_SCHEDULER: bool = True
    GCP_PROJECT: Optional[str] = None
    IMAGE_TAG: Optional[str] = None


settings = Settings()
