"""Settings, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite for local dev; a Postgres URL (Supabase) in production.
    database_url: str = "sqlite:///./monsterbox.db"

    # Supabase project JWT settings (Dashboard -> Settings -> API).
    supabase_jwt_secret: str = ""        # legacy HS256 secret (optional)
    supabase_jwt_aud: str = "authenticated"
    # Project base URL, e.g. https://<ref>.supabase.co. Optional: if blank it's
    # derived from DATABASE_URL. Used to find the public keys (JWKS) for the
    # modern asymmetric (ES256) login tokens.
    supabase_url: str = ""

    # Local-only escape hatch: trust an X-Dev-User header instead of a real token.
    dev_auth: bool = False

    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://127.0.0.1:8077"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
