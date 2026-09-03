from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    migrate_database_url: str | None = None
    secret_key: str

    admin_username: str = "admin"
    admin_password: str

    log_level: str = "INFO"
    tz: str = "Europe/Rome"

    session_duration_hours: int = 12
    login_lockout_attempts: int = 5
    login_lockout_minutes: int = 15
    password_min_length: int = 12

    extract_enabled: bool = True
    extract_mode: Literal["text", "vision"] = "text"
    # phi4-mini confondeva i campi della tabella e sulle pagine lunghe degenerava
    # in ripetizione; qwen3:4b legge la stessa bolla correttamente (Apache-2.0,
    # in whitelist licenze).
    extract_model: str = "qwen3:4b"
    ollama_base_url: str = "http://ollama:11434"
    # Una bolla intera sta in 2000-3000 token di prompt; l'uscita cresce con il
    # numero di seriali: una pagina fitta può portarne alcune decine.
    extract_num_ctx: int = 8192
    extract_num_predict: int = 4096
    # Generoso di proposito: senza GPU la stessa analisi passa da secondi a
    # minuti, e gira comunque in sottofondo senza bloccare nessuno.
    extract_timeout_seconds: float = 900.0
    extract_allow_heic: bool = False
    extraction_log_retention_days: int = 90
    extraction_rate_limit_per_minute: int = 30

    login_rate_limit_per_minute: int = 10
    request_rate_limit_per_minute: int = 300

    max_image_bytes: int = 15 * 1024 * 1024
    max_images_per_request: int = 5

    # Previsto in progetto (endpoint `/metrics` in formato Prometheus,
    # spento di default) ma **non ancora implementato**: l'impostazione esiste
    # perché il deploy la passa già, e accenderla oggi non fa comparire nulla.
    metrics_enabled: bool = False

    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
