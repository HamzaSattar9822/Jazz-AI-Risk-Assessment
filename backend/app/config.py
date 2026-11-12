from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./aira.db"
    jwt_secret: str = "dev-only-change-me"
    jwt_expire_minutes: int = 720
    governance_email: str = "sana.malik@jazz.example"

    # Mail: auto | log | smtp | graph
    # auto = Graph if configured, else Outlook SMTP, else log-only.
    mail_provider: str = "auto"
    mail_enabled: bool = True
    mail_timeout_seconds: float = 30
    mail_reply_to: str = ""

    # Outlook / Microsoft 365 SMTP (smtp.office365.com)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "raio@jazz.example"
    smtp_tls: bool = True

    # Microsoft Graph (Entra ID app + Mail.Send)
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_sender: str = ""
    llm_base_url: str = (
        "https://qwen38-27b-meter.apps.aiops.jazz.com.pk/v1"
    )
    llm_api_key: str = ""
    llm_model: str = "qwen38-27b"
    llm_json_mode: bool = True
    llm_timeout_seconds: float = 60
    # Jazz AIOps serves a corporate TLS chain; verification is off by default.
    llm_verify_ssl: bool = False
    # Meter gateway requires a Jazz bearer token.
    llm_require_api_key: bool = True
    cors_origins: str = (
        "http://localhost:8080,http://127.0.0.1:8080,http://10.124.50.231:8080"
    )
    duplicate_threshold: int = 90

    # Microsoft Entra ID (OIDC SSO)
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_redirect_uri: str = ""
    # Comma-separated allowed app role values from the Entra roles claim.
    entra_allowed_roles: str = "requester,reviewer,admin"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        if not self.llm_base_url:
            return False
        if self.llm_require_api_key and not self.llm_api_key:
            return False
        return True

    @property
    def entra_configured(self) -> bool:
        return bool(
            self.entra_tenant_id
            and self.entra_client_id
            and self.entra_client_secret
            and self.entra_redirect_uri
        )

    @property
    def entra_allowed_role_set(self) -> set[str]:
        return {
            part.strip().lower()
            for part in self.entra_allowed_roles.split(",")
            if part.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
