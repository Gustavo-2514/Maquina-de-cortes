"""Uso de disco e limpeza de arquivos temporários/regeneráveis (Configurações → Armazenamento)."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, col, select

from .config import get_settings
from .models import Clip, Project

TEMP_GLOBS = ("*.part", "*.ytdl", "*-Frag*", "*.tmp", "*.tmp.*", "render.tmp.mp4", "upload.*.part")


def dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*") if p.exists() else []:
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _temp_files(data: Path) -> list[Path]:
    out: set[Path] = set()
    for sub in ("downloads", "projects", "exports"):
        base = data / sub
        for pattern in TEMP_GLOBS:
            out.update(f for f in base.rglob(pattern) if f.is_file())
    return sorted(out)


def _orphans(session: Session, data: Path) -> list[Path]:
    """Pastas de projetos/cortes que não existem mais no banco."""
    pids = {p for p in session.exec(select(Project.id)).all()}
    cids = {c for c in session.exec(select(Clip.id)).all()}
    out = []
    for d in (data / "projects").iterdir() if (data / "projects").exists() else []:
        if not d.is_dir():
            continue
        if not d.name.isdigit() or int(d.name) not in pids:
            out.append(d)
            continue
        for c in (d / "clips").iterdir() if (d / "clips").exists() else []:
            if c.is_dir() and (not c.name.isdigit() or int(c.name) not in cids):
                out.append(c)
    return out


def _last_activity(session: Session, p: Project) -> datetime:
    last = session.exec(select(Clip.updated_at).where(Clip.project_id == p.id)
                        .order_by(col(Clip.updated_at).desc()).limit(1)).first()
    times = [t for t in (p.updated_at, last) if t is not None]
    return max(t if t.tzinfo else t.replace(tzinfo=UTC) for t in times)


def _candidates(session: Session, proxy_days: int) -> dict[str, list[tuple[Path, int | None]]]:
    data = get_settings().data_dir
    audio, proxies = [], []
    horizon = datetime.now(UTC) - timedelta(days=proxy_days)
    for p in session.exec(select(Project).where(Project.status == "ready")).all():
        pdir = get_settings().project_dir(p.id)  # type: ignore[arg-type]
        if (pdir / "audio.wav").exists():
            audio.append((pdir / "audio.wav", p.id))
        if (pdir / "proxy.mp4").exists() and _last_activity(session, p) < horizon:
            proxies.append((pdir / "proxy.mp4", p.id))
    temp = [(f, None) for f in _temp_files(data)] + [(d, None) for d in _orphans(session, data)]
    return {"temp": temp, "audio": audio, "proxies": proxies}


def report(session: Session, proxy_days: int = 30) -> dict:
    s = get_settings()
    data = s.data_dir
    usage = shutil.disk_usage(data)
    cands = _candidates(session, proxy_days)
    return {
        "data_dir": str(data),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "folders": {k: dir_size(data / k) for k in ("downloads", "projects", "exports", "logs")},
        "cleanable": {k: {"bytes": sum(dir_size(p) for p, _ in v), "count": len(v),
                          "projects": sorted({pid for _, pid in v if pid is not None})} for k, v in cands.items()},
        "proxy_days": proxy_days,
    }


def cleanup(session: Session, temp: bool, audio: bool, proxies: bool, proxy_days: int = 30) -> dict:
    data = get_settings().data_dir.resolve()
    cands = _candidates(session, proxy_days)
    freed = removed = 0
    for key, enabled in (("temp", temp), ("audio", audio), ("proxies", proxies)):
        if not enabled:
            continue
        for path, _pid in cands[key]:
            rp = path.resolve()
            if not rp.is_relative_to(data):
                continue  # nunca apaga fora de data/
            size = dir_size(rp)
            try:
                if rp.is_dir():
                    shutil.rmtree(rp)
                else:
                    rp.unlink()
            except OSError:
                continue
            freed += size
            removed += 1
    return {"freed_bytes": freed, "removed": removed}
