"""Configuração do app.

Duas camadas:
- `Settings` (pydantic-settings): caminhos e parâmetros de infraestrutura, lidos de
  variáveis de ambiente com prefixo `MDC_` (ex.: `MDC_PORT=8001`).
- `UserSettings`: preferências editáveis na tela de Configurações, persistidas em
  `data/settings.json`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # maquina-de-cortes/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MDC_", env_file=ROOT_DIR / ".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = ROOT_DIR / "data"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    def project_dir(self, project_id: int) -> Path:
        return self.data_dir / "projects" / str(project_id)

    def ensure_dirs(self) -> None:
        for sub in ("downloads", "projects", "exports", "logs"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


class UserSettings(BaseModel):
    """Preferências do usuário (tela Configurações). 'auto' = decidir pelo hardware."""

    whisper_model: str = "auto"
    whisper_device: Literal["auto", "cuda", "cpu"] = "auto"
    whisper_compute_type: str = "auto"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    encoder: Literal["auto", "nvenc", "x264"] = "auto"
    export_dir: str = ""  # vazio = data/exports
    normalize_audio: bool = True  # loudnorm -14 LUFS (padrão das redes)
    default_language: str = "pt"
    cookies_path: str = ""


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def load_user_settings() -> UserSettings:
    path = get_settings().settings_file
    if path.exists():
        try:
            return UserSettings.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            pass  # arquivo corrompido → volta ao padrão
    return UserSettings()


def save_user_settings(us: UserSettings) -> None:
    path = get_settings().settings_file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(us.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
