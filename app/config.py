from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # AI / APIs
    OPENROUTER_KEY: str = ""
    TAVILY_KEY: str = ""
    UNSPLASH_KEY: str = ""

    # Telegram
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["https://ikshan.in", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
