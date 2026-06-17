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

    # "Report an issue" delivery. Reports are always saved to the DB; if SMTP is
    # configured they're ALSO emailed (with the screenshot attached). Works with
    # any SMTP host (a Gmail app password is the most reliable).
    report_to: str = "monsterboxdev@outlook.com"
    report_smtp_host: str = ""
    report_smtp_port: int = 587
    report_smtp_user: str = ""
    report_smtp_password: str = ""
    report_from: str = ""            # defaults to report_smtp_user if blank
    # Resend HTTP API key (re_...). Optional: if blank but the SMTP password is a
    # Resend key, that's reused. The HTTP path avoids hosts that block SMTP ports.
    report_resend_api_key: str = ""

    # BETA-ONLY: auto-collect PDFs that signed-in testers import, for parser testing.
    # Set false (or remove) when leaving beta. Bytes only stored up to the cap (MB).
    beta_collect_pdfs: bool = True
    beta_pdf_max_mb: int = 250       # per-file cap (bigger files: metadata only)
    beta_pdf_total_mb: int = 450     # total stored-bytes budget; over this = metadata only

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def smtp_ready(self) -> bool:
        return bool(self.report_smtp_host and self.report_smtp_user and self.report_smtp_password)

    @property
    def email_ready(self) -> bool:
        """Can we send email at all — via SMTP, or the Resend HTTP API?"""
        resend_http = bool(self.report_to) and (
            bool(self.report_resend_api_key)
            or ("resend.com" in self.report_smtp_host.lower() and self.report_smtp_password.startswith("re_"))
        )
        return self.smtp_ready or resend_http


settings = Settings()
