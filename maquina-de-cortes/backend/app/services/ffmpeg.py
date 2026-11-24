"""Execução do ffmpeg com progresso (-progress pipe:1) e cancelamento."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path


class FFmpegError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class FFmpegCanceled(Exception):
    pass


def run_ffmpeg(
    args: list[str],
    duration_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    register_process: Callable[[subprocess.Popen], None] | None = None,
    is_canceled: Callable[[], bool] | None = None,
    cwd: Path | None = None,
    error_message: str = "Falha no FFmpeg",
) -> None:
    """Roda `ffmpeg <args>`; chama on_progress(0-100) a partir de out_time. Lança FFmpegError/FFmpegCanceled."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args]
    stderr_tail: deque[str] = deque(maxlen=40)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, errors="replace")
    if register_process:
        register_process(p)

    def drain() -> None:
        assert p.stderr
        for line in p.stderr:
            stderr_tail.append(line.rstrip())

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    assert p.stdout
    for line in p.stdout:
        if is_canceled and is_canceled():
            p.terminate()
            break
        key, _, val = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms") and duration_s and on_progress:
            try:
                secs = int(val) / 1_000_000  # out_time_ms também é em µs (bug histórico do ffmpeg)
            except ValueError:
                continue
            on_progress(max(0.0, min(100.0, 100.0 * secs / duration_s)))
    p.wait()
    t.join(timeout=2)
    if is_canceled and is_canceled():
        raise FFmpegCanceled()
    if p.returncode != 0:
        raise FFmpegError(error_message, "\n".join(stderr_tail) or f"ffmpeg saiu com código {p.returncode}")
