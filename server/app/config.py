"""Settings, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite for local dev; a Postgres URL (Supabase) in production.
    database_url: str = "sqlite:///./monsterbox.db"

    # Supabase project JWT settings (Dashboard -> Settings -> API).
    supabase_jwt_secret: str = ""
    supabase_jwt_aud: str = "authenticated"

    # Local-only escape hatch: trust an X-Dev-User header instead of a real token.
    dev_auth: bool = False

    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://127.0.0.1:8077"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
