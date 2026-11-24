"""Streaming de arquivos de data/ com HTTP Range (o <video> precisa disso para seek)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import get_settings

router = APIRouter(tags=["media"])


def resolve_media(rel: str) -> Path:
    data = get_settings().data_dir.resolve()
    if "\x00" in rel:
        raise HTTPException(400, "Caminho inválido")
    path = (data / rel).resolve()
    if not path.is_relative_to(data):  # bloqueia ../ e caminhos absolutos
        raise HTTPException(403, "Fora da pasta de dados")
    if not path.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return path


@router.get("/media/{rel:path}")
def media(rel: str) -> FileResponse:
    # FileResponse do Starlette responde Range com 206 Partial Content
    return FileResponse(resolve_media(rel), headers={"Cache-Control": "no-cache"})
