from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HoneyAI Live Backend"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_voice_name: str = "Aoede"
    vision_model: str = "gemini-2.5-flash"
    enable_gemini_live: bool = False
    gemini_thinking_budget: int = 0
    database_url: str = "sqlite:///backend/data/honeyai.db"
    allowed_origins: str = Field(default="http://localhost:3000,http://localhost:3001,*")
    stm_limit: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def sqlite_path(self) -> Path:
        raw_path = self.database_url.replace("sqlite:///", "", 1)
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / raw_path
        return path

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
