import os


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    """Environment-only settings for the public portfolio edition."""

    APP_ENV: str = os.getenv("APP_ENV", "development").lower()
    DB_HOST: str = os.getenv("DB_HOST", "db.example.internal")
    DB_PATH: str = os.getenv("DB_PATH", "/data/DEMO.FDB")
    DB_USER: str = os.getenv("DB_USER", "demo_user")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_CHARSET: str = os.getenv("DB_CHARSET", "WIN1252")
    API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_KEY: str = os.getenv("API_KEY", "")
    DEBUG_LOG: bool = os.getenv("DEBUG_LOG", "false").lower() in {"1", "true", "yes"}

    def validate_runtime(self) -> None:
        if not self.DB_PASSWORD:
            raise RuntimeError("DB_PASSWORD must be supplied at runtime")
        if not self.API_KEY or len(self.API_KEY) < 16:
            raise RuntimeError("API_KEY must be supplied and contain at least 16 characters")


settings = Settings()
