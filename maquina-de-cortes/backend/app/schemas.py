"""DTOs de request/response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FormatChoice = Literal["best", "1080p", "720p", "audio_mp3"]


class InfoRequest(BaseModel):
    url: str = Field(min_length=4)


class DownloadCreate(BaseModel):
    url: str = Field(min_length=4)
    format_choice: FormatChoice = "best"
    send_to_project: bool = False
    # metadados já obtidos no /info (evita mostrar a linha vazia até o worker começar)
    title: str = ""
    uploader: str = ""
    duration_s: float | None = None
    thumbnail_url: str = ""
    # opções da análise do projeto criado ao terminar (send_to_project); None = padrões
    analyze: AnalysisOptions | None = None


class DownloadBatch(BaseModel):
    items: list[DownloadCreate] = Field(min_length=1, max_length=500)


class PathRequest(BaseModel):
    path: str


class AnalysisOptions(BaseModel):
    num_clips: int = Field(default=10, ge=1, le=50)
    min_s: float = Field(default=60, ge=5, le=600)
    max_s: float = Field(default=90, ge=10, le=900)
    extra_prompt: str = Field(default="", max_length=2000)
    language: str = "pt"  # "auto" = detectar
    caption_style: str = "hormozi"
    reframe_mode: Literal["auto", "speaker", "center", "blur_fit", "split", "gameplay"] = "auto"
    template: str = "geral"  # geral | gameplay | podcast | debate (services/templates.py)
    llm: str = "ollama"  # "ollama" (local, grátis) ou a ref de um modelo pago (services/ai.py)
    auto_render: bool = False  # ao terminar a análise, já renderiza todos os cortes (etapa "render")


class ProjectCreate(BaseModel):
    download_id: int | None = None
    local_path: str | None = None
    name: str = ""
    language: str | None = None  # None = idioma padrão das Configurações
    analyze: AnalysisOptions | None = None  # se vier, já enfileira a análise


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = None


class ClipCreate(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    title: str = Field(default="", max_length=200)


class ClipUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    hook_text: str | None = None
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    status: Literal["suggested", "edited", "discarded"] | None = None
    reframe_mode: Literal["auto", "speaker", "center", "blur_fit", "split", "gameplay", "manual"] | None = None
    manual_crop_json: str | None = None
    layout_json: str | None = None
    caption_style_id: int | None = None
    caption_overrides_json: str | None = None
    export_json: str | None = None
    title_overlay: str | None = Field(default=None, max_length=200)


_HEX = r"^#[0-9A-Fa-f]{6}$"


class CaptionStyleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    font: str = "Montserrat ExtraBold"
    font_size: int = Field(default=88, ge=20, le=240)
    primary_color: str = Field(default="#FFFFFF", pattern=_HEX)
    highlight_color: str = Field(default="#FFE600", pattern=_HEX)
    outline_color: str = Field(default="#000000", pattern=_HEX)
    outline_px: float = Field(default=6, ge=0, le=30)
    shadow_px: float = Field(default=0, ge=0, le=30)
    uppercase: bool = True
    words_per_line: int = Field(default=2, ge=1, le=4)
    position_y: float = Field(default=0.68, ge=0.05, le=0.95)
    animation: Literal["highlight", "pop", "karaoke", "none"] = "highlight"


class CaptionStyleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    font: str | None = None
    font_size: int | None = Field(default=None, ge=20, le=240)
    primary_color: str | None = Field(default=None, pattern=_HEX)
    highlight_color: str | None = Field(default=None, pattern=_HEX)
    outline_color: str | None = Field(default=None, pattern=_HEX)
    outline_px: float | None = Field(default=None, ge=0, le=30)
    shadow_px: float | None = Field(default=None, ge=0, le=30)
    uppercase: bool | None = None
    words_per_line: int | None = Field(default=None, ge=1, le=4)
    position_y: float | None = Field(default=None, ge=0.05, le=0.95)
    animation: Literal["highlight", "pop", "karaoke", "none"] | None = None


class CleanupRequest(BaseModel):
    temp: bool = True
    audio: bool = False
    proxies: bool = False
    proxy_days: int = Field(default=30, ge=0, le=3650)


class OllamaTest(BaseModel):
    url: str
    model: str


class ApplyTemplate(BaseModel):
    template: str
    render: bool = False  # já enfileira o render de todos os cortes ativos


class PostPackRequest(BaseModel):
    """Pacote para postar: o que (re)gerar. No projeto, `only_missing` pula o que já existe."""

    texts: bool = True
    cover: bool = True
    only_missing: bool = True


class PostTexts(BaseModel):
    """Edição manual dos textos: {"caption", "hashtags"} (tiktok/reels) e {"title", "description", "hashtags"} (shorts)."""

    tiktok: dict = Field(default_factory=dict)
    reels: dict = Field(default_factory=dict)
    shorts: dict = Field(default_factory=dict)


class AiKeyTest(BaseModel):
    provider: str
    api_key: str = ""  # vazio/mascarado = a chave salva
    base_url: str = ""  # só para o provedor "custom" (vazio = o salvo)


class ClaudeTest(BaseModel):
    api_key: str = ""  # vazio/mascarado = a chave salva
    model: str = "claude-haiku-5-5"


class ReviewSubmit(BaseModel):
    """Revisão feita fora do app (Claude Code no plano Pro): mesmo formato do job `review`."""

    verdict: str
    summary: str = ""
    issues: list[dict] = Field(default_factory=list)
    model: str = "Claude Code (plano Pro)"
    tokens_approx: int = 0  # estimativa de uso do plano (não é cobrado em US$)


class ReviewRequest(BaseModel):
    """Revisão visual por IA paga. No projeto, `only_missing` pula cortes já revisados neste render."""

    model: str = ""  # ref do modelo (services/ai.py); vazio = o padrão das Configurações
    only_missing: bool = True
