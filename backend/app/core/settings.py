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
    storage_max_file_bytes: Annotated[int, Field(ge=1, le=200 * 1024 * 1024)] = 20 * 1024 * 1024
    worker_lease_seconds: Annotated[int, Field(ge=5, le=3600)] = 30
    worker_heartbeat_seconds: Annotated[float, Field(ge=0.1)] = 5
    worker_poll_seconds: Annotated[float, Field(ge=0.1, le=60)] = 2
    model_provider: str = ""
    model_name: str = ""
    model_base_url: str = ""
    model_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def local_config(self):
        if self.app_port == self.frontend_port:
            raise ValueError("APP_PORT and FRONTEND_PORT must differ")
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds / 2:
            raise ValueError("Worker heartbeat must be less than half its lease")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("V1 local mode expects a local SQLite URL")
        from backend.app.repositories.database import database_path
        database_path(self.database_url)
        from backend.app.storage import LocalStorage
        configured = self.storage_root if self.storage_root.is_absolute() else ROOT/self.storage_root
        self.storage_root = LocalStorage(configured, max_bytes=self.storage_max_file_bytes).root
        if any(self.storage_root.resolve().is_relative_to((ROOT/name).resolve()) for name in ("frontend", "contracts")):
            raise ValueError("Private storage cannot be inside frontend or served contract directories")
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
