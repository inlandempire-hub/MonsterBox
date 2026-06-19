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
    # DB-storage fallback (used only when Supabase Storage isn't configured). Per-file
    # cap kept modest: the file is held in RAM while it's stored, and the free tier
    # only has 512MB (250MB OOM'd it). Bigger books record metadata only.
    beta_pdf_max_mb: int = 40
    beta_pdf_total_mb: int = 450     # total DB stored-bytes budget; over this = metadata only

    # PREFERRED storage: Supabase Storage (object storage). When the service key is
    # set, collected PDFs are streamed there instead of into the DB — large files
    # work without using the app's RAM, and downloads are signed URLs served direct
    # from Supabase. service_role key: Supabase Dashboard -> Settings -> API.
    supabase_service_key: str = ""
    beta_storage_bucket: str = "beta_pdfs"   # matches the bucket created in Supabase
    beta_storage_max_mb: int = 300       # per-file cap on the storage path
    beta_storage_total_mb: int = 900     # total budget (Supabase free Storage ~1GB)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_base(self) -> str:
        """Project base URL (https://<ref>.supabase.co): explicit, else derived from
        the Postgres DATABASE_URL (username 'postgres.<ref>')."""
        if self.supabase_url:
            return self.supabase_url.rstrip("/")
        try:
            from sqlalchemy.engine import make_url
            user = make_url(self.database_url).username or ""
            if user.startswith("postgres."):
                return f"https://{user.split('.', 1)[1]}.supabase.co"
        except Exception:
            pass
        return ""

    @property
    def storage_ready(self) -> bool:
        return bool(self.supabase_service_key and self.supabase_base)

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
