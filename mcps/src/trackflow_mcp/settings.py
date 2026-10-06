from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    mcp_public_url: str = "http://localhost:8001"
    mcp_audience: str = "trackflow-mcp"
    mcp_required_scope: str = "trackflow:mcp"

    oauth_issuer_url: str = "http://localhost:8080/realms/trackflow"
    oauth_authorization_endpoint: str | None = None
    oauth_token_endpoint: str | None = None
    oauth_jwks_uri: str = "http://keycloak:8080/realms/trackflow/protocol/openid-connect/certs"

    trackflow_api_base_url: str = "http://127.0.0.1:8000"
    trackflow_service_username: str = ""
    trackflow_service_password: str = ""

    @property
    def issuer(self) -> str:
        return self.oauth_issuer_url.rstrip("/")

    @property
    def authorization_endpoint(self) -> str:
        return self.oauth_authorization_endpoint or (
            f"{self.issuer}/protocol/openid-connect/auth"
        )

    @property
    def token_endpoint(self) -> str:
        return self.oauth_token_endpoint or (
            f"{self.issuer}/protocol/openid-connect/token"
        )

    @property
    def jwks_uri(self) -> str:
        return self.oauth_jwks_uri

    @property
    def mcp_resource_url(self) -> str:
        return f"{self.mcp_public_url.rstrip('/')}/mcp"


settings = Settings()