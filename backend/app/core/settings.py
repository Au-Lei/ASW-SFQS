"""Server-only configuration. Never serialize Settings to an API response."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT/".env", ROOT/".env.local"), env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )
    app_env: Literal["development", "local"] = "development"
    app_host: Literal["127.0.0.1"] = "127.0.0.1"
    app_port: Annotated[int, Field(ge=1024, le=65535)] = 8000
    frontend_port: Annotated[int, Field(ge=1024, le=65535)] = 5173
    app_timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    database_url: str = "sqlite:///./data/app.sqlite3"
    storage_root: Path = ROOT/"data"
    model_provider: str = ""
    model_name: str = ""
    model_base_url: str = ""
    model_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def local_config(self):
        if self.app_port == self.frontend_port:
            raise ValueError("APP_PORT and FRONTEND_PORT must differ")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("V1 local mode expects a local SQLite URL")
        from backend.app.repositories.database import database_path
        database_path(self.database_url)
        if not self.storage_root.is_absolute():
            self.storage_root = (ROOT/self.storage_root).resolve()
        return self

    @property
    def allowed_authorities(self) -> set[str]:
        ports = [self.app_port]
        if self.app_env == "development":
            ports.append(self.frontend_port)
        return {f"{host}:{port}" for host in ("127.0.0.1", "localhost") for port in ports}

    @property
    def allowed_origins(self) -> set[str]:
        return {"http://"+host for host in self.allowed_authorities}

    @property
    def model_status(self) -> Literal["NOT_CONFIGURED", "ADAPTER_NOT_IMPLEMENTED"]:
        configured = all((self.model_provider.strip(), self.model_name.strip(), self.model_api_key.get_secret_value().strip()))
        return "ADAPTER_NOT_IMPLEMENTED" if configured else "NOT_CONFIGURED"
