from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import clips, downloads, jobs, media, projects, system
from .config import get_settings
from .db import init_db
from .events import broker
from .logging_setup import setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging("api")
    init_db()
    broker.start()
    yield
    await broker.stop()


app = FastAPI(title="Máquina de Cortes", lifespan=lifespan)
app.include_router(system.router, prefix="/api")
app.include_router(downloads.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(media.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# --- Frontend (build do Vite) -------------------------------------------------
dist = settings.frontend_dist
# fontes das legendas: o preview do editor usa os mesmos .ttf que o libass no render
from .services.renderer import FONTS_DIR  # noqa: E402

app.mount("/api/fonts", StaticFiles(directory=FONTS_DIR), name="fonts")

if (dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    candidate = (dist / full_path).resolve()
    if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
        return FileResponse(candidate)
    index = dist / "index.html"
    if not index.exists():
        raise HTTPException(503, "Frontend não buildado. Rode: cd frontend && npm install && npm run build")
    return FileResponse(index)  # rotas do React Router
