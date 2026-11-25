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

from pydantic import BaseModel, model_validator
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


class AiModel(BaseModel):
    """Modelo de um provedor compatível com a API da OpenAI (OpenAI, Gemini, OpenRouter…) adicionado pelo usuário.

    Preços em US$ por milhão de tokens; None = desconhecido (o app mostra os tokens, mas não estima em US$).
    No OpenRouter vêm do catálogo público; nos outros, o usuário informa."""

    provider: str
    id: str
    label: str = ""
    input_per_mtok: float | None = None
    output_per_mtok: float | None = None
    vision: bool = True  # aceita imagens (necessário para a revisão visual)
    prices_as_of: str = ""


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
    # Claude (opcional, pago): vazio = usa ANTHROPIC_API_KEY do ambiente. Nunca sai deste computador
    # a não ser para a própria API da Anthropic.
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"  # legado: modelo da revisão visual antes de existir `review_model`
    # Outros provedores pagos (services/ai.py): chave por provedor ("openai", "gemini", "openrouter"…);
    # vazia = variável de ambiente do provedor (OPENAI_API_KEY etc.). Mesma regra: só vai para a API do provedor.
    api_keys: dict[str, str] = {}
    custom_base_url: str = ""  # provedor "custom": qualquer API compatível com a OpenAI (LM Studio, Together…)
    ai_models: list[AiModel] = []
    review_model: str = ""  # ref do modelo padrão da revisão visual ("claude-opus-5-5", "openrouter:openai/gpt-…")

    @model_validator(mode="after")
    def _migrate(self) -> UserSettings:
        if not self.review_model:
            self.review_model = self.claude_model
        return self


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
