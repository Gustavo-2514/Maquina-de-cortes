"""Tabelas SQLModel (seção 5 da especificação).

Fase 1: Download e Job. Fase 2: Project. Fase 3: Clip. Fase 4: CaptionStyle.
`updated_at` existe em todas as tabelas que vão para o SSE: a API faz polling por
`updated_at > cursor` para publicar mudanças feitas pelo worker (outro processo).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(UTC)


class Download(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    url: str
    title: str = ""
    uploader: str = ""
    duration_s: float | None = None
    thumbnail_url: str = ""
    format_choice: str = "best"  # best | 1080p | 720p | audio_mp3
    status: str = Field(default="queued", index=True)  # queued|downloading|done|error|canceled
    progress: float = 0
    speed: str = ""
    eta: str = ""
    file_path: str = ""
    filesize: int | None = None
    error: str = ""
    error_detail: str = ""
    send_to_project: bool = False
    project_id: int | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str = Field(index=True)  # download|probe_proxy|transcribe|analyze|reframe|render
    ref_id: int  # download_id / project_id / clip_id
    status: str = Field(default="queued", index=True)  # queued|running|done|error|canceled
    progress: float = 0
    message: str = ""
    error: str = ""
    error_detail: str = ""
    uses_gpu: bool = False
    priority: int = 0  # maior = antes
    created_at: datetime = Field(default_factory=now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=now, index=True)


class Project(SQLModel, table=True):
    """Um vídeo-fonte que vai virar cortes. Arquivos derivados ficam em data/projects/<id>/."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    source_path: str
    origin: str = "download"  # download | upload | local_path
    download_id: int | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = True
    language: str = "pt"  # "auto" = detectar
    status: str = Field(default="new", index=True)  # new|processing|ready|error
    stage: str = "probe"  # probe|proxy|transcribe|analyze|done
    progress: float = 0  # progresso da etapa atual (0-100)
    error: str = ""
    error_detail: str = ""
    settings_json: str = "{}"  # opções da análise
    detected_language: str = ""
    word_count: int = 0
    faces_ready: bool = False  # cenas + rostos analisados (reenquadramento automático)
    prepare_only: bool = False  # job atual só restaura arquivos limpos (não refaz transcrição/análise)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)


class Clip(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="project.id", ondelete="CASCADE")
    title: str = ""
    hook_text: str = ""
    reason: str = ""
    start_s: float
    end_s: float
    score: float = 0  # 0-100
    score_breakdown_json: str = "{}"  # {gancho, emocao, clareza, completude, heuristica, llm}
    status: str = Field(default="suggested", index=True)  # suggested|edited|rendering|rendered|error|discarded
    origin: str = "ai"  # ai | manual
    reframe_mode: str = "auto"  # auto|speaker|center|blur_fit|split|gameplay|manual
    manual_crop_json: str = "[]"
    layout_json: str = "{}"  # gameplay: {"top_ratio", "cam_center": [x, y], "cam_w", "game_cx"}
    caption_style_id: int | None = None
    caption_overrides_json: str = "{}"  # {"words": {"<s 3 casas>": texto}, "style": {...}, "title_until": 3|null}
    export_json: str = "{}"  # {"quality": "high"|"normal"|"small", "normalize_audio": bool}
    title_overlay: str = ""
    output_path: str = ""
    error: str = ""
    rendered_at: datetime | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now, index=True)


class CaptionStyle(SQLModel, table=True):
    """Preset de legenda. Cores em #RRGGBB (o ASS usa BGR; a conversão fica no captions.py)."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(default="", index=True)  # identificador estável dos embutidos (hormozi, clean…)
    name: str
    font: str = "Montserrat ExtraBold"
    font_size: int = 88
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    outline_color: str = "#000000"
    outline_px: float = 6
    shadow_px: float = 0
    uppercase: bool = True
    words_per_line: int = 2
    position_y: float = 0.68  # centro da legenda, 0 = topo, 1 = base
    animation: str = "highlight"  # highlight | pop | karaoke | none
    is_builtin: bool = False
    updated_at: datetime = Field(default_factory=now, index=True)


# "reframe" (cenas + rostos) roda na CPU: fica no slot leve, em paralelo com a transcrição na GPU
GPU_JOB_TYPES = {"transcribe", "analyze", "render"}
