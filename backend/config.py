from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MAX Support Backend"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    max_bot_token: str = ""

    database_url: str = "sqlite:///./data/app.db"
    cors_origins_raw: str = "*"
    public_domain: str = ""
    public_webapp_url: str = ""
    public_api_base_url: str = ""
    max_session_secret: str = ""

    osticket_api_url: str = ""
    osticket_api_key: str = ""
    osticket_request_timeout: int = 20
    osticket_status_api_url: str = ""
    osticket_extended_api_url: str = ""
    osticket_extended_api_staff_id: int = 1
    osticket_extended_api_status_open_id: int = 1
    osticket_extended_api_status_close_id: int = 3
    osticket_extended_api_team_id: int = 1
    osticket_extended_api_dept_id: int = 1
    osticket_extended_api_topic_id: int = 1
    osticket_extended_api_username: str = ""
    email_verification_ttl_minutes: int = 10
    max_webapp_auth_max_age_seconds: int = 86400
    max_session_ttl_seconds: int = 0
    internal_api_token: str = ""
    ticket_status_poll_interval_seconds: int = 60
    ticket_dedup_seconds: int = 30

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    allowed_email_domains_raw: str = Field(default="", alias="ALLOWED_EMAIL_DOMAINS")
    admin_max_ids_raw: str = Field(default="", alias="ADMIN_MAX_IDS")

    @property
    def cors_origins(self) -> List[str]:
        raw = self.cors_origins_raw.strip()
        if not raw:
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def allowed_email_domains(self) -> List[str]:
        raw = getattr(self, "allowed_email_domains_raw", "").strip()
        if not raw:
            return []
        return [item.strip().lower() for item in raw.split(",") if item.strip()]

    @property
    def admin_max_ids(self) -> List[str]:
        raw = self.admin_max_ids_raw.strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
