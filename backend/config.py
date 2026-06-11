from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Base de datos
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/zipgrade_db"

    # Cloudflare R2
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: str = ""
    R2_BUCKET: str = "zipgrade-pdfs"
    R2_PUBLIC_URL: str = ""

    # Anthropic (Claude Vision)
    ANTHROPIC_API_KEY: str = ""

    # Telegram
    BOT_PROFE_TOKEN: str = ""
    BOT_ESTUDIANTE_TOKEN: str = ""

    # App
    SECRET_KEY: str = "cambia-esto-en-produccion"
    DEBUG: bool = False

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
