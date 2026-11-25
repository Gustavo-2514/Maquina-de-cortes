from __future__ import annotations

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from ..config import UserSettings, get_settings, load_user_settings, save_user_settings
from ..schemas import ClaudeTest, CleanupRequest, OllamaTest, PathRequest
from ..services import hardware

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/check")
async def system_check() -> dict:
    us = load_user_settings()
    # checks chamam subprocessos/HTTP: fora do event loop
    return await run_in_threadpool(hardware.run_checks, get_settings().data_dir, us.ollama_url, us.ollama_model)


MASK = "••••"


def _masked(us: UserSettings) -> UserSettings:
    """A chave da Anthropic nunca volta inteira para o navegador: só os 4 últimos caracteres."""
    k = us.anthropic_api_key
    return us.model_copy(update={"anthropic_api_key": f"{MASK}{k[-4:]}" if k else ""})


def _real_key(sent: str) -> str:
    return load_user_settings().anthropic_api_key if sent.startswith(MASK) else sent.strip()


@router.get("/settings", response_model=UserSettings)
def get_user_settings() -> UserSettings:
    return _masked(load_user_settings())


@router.put("/settings", response_model=UserSettings)
def put_user_settings(body: UserSettings) -> UserSettings:
    body.anthropic_api_key = _real_key(body.anthropic_api_key)
    save_user_settings(body)
    return _masked(body)


@router.get("/claude/models")
def claude_models() -> dict:
    from ..services import claude

    return {"default": claude.DEFAULT_MODEL, "prices_as_of": claude.PRICES_AS_OF,
            "models": [{"id": m, "label": claude.MODEL_LABELS[m], "input_per_mtok": p[0], "output_per_mtok": p[1]}
                       for m, p in claude.PRICES.items()]}


@router.post("/claude/test")
def claude_test(body: ClaudeTest) -> dict:
    """Pedido mínimo para validar a chave (custa uma fração de centavo — o valor real volta na resposta)."""
    from ..services import claude
    from ..services.highlighter import HighlightError

    meter = claude.CostMeter()
    try:
        claude.create(claude.make_client(_real_key(body.api_key)), body.model, "Responda só o JSON pedido.",
                      "Diga ok.", {"type": "object", "properties": {"ok": {"type": "boolean"}}}, meter,
                      effort="low", max_tokens=1024)
    except HighlightError as e:
        return {"ok": False, "message": str(e), "detail": e.detail}
    return {"ok": True, "message": f"Chave válida ({body.model}).", "cost": meter.as_dict()}


@router.get("/ytdlp")
def ytdlp_version() -> dict:
    import yt_dlp

    return {"version": yt_dlp.version.__version__}


@router.post("/update-ytdlp")
def update_ytdlp() -> dict:
    """Atualiza o yt-dlp no venv (sites mudam com frequência). Requer reiniciar o app para o worker usar."""
    import shutil
    import subprocess
    import sys

    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", sys.executable, "-U", "yt-dlp[default]"] if uv
           else [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(500, f"Falha ao atualizar: {e}") from e
    if r.returncode != 0:
        raise HTTPException(500, {"message": "Falha ao atualizar o yt-dlp", "detail": (r.stderr or r.stdout)[-2000:]})
    v = subprocess.run([sys.executable, "-c", "import yt_dlp; print(yt_dlp.version.__version__)"],
                       capture_output=True, text=True, timeout=60).stdout.strip()
    return {"version": v, "output": (r.stderr + r.stdout)[-2000:], "restart_required": True}


@router.post("/open-folder")
def open_folder(body: PathRequest) -> dict:
    """Abre no gerenciador de arquivos a pasta de um caminho dentro de data/ (app local)."""
    import subprocess
    import sys
    from pathlib import Path

    data = get_settings().data_dir.resolve()
    roots = [data]
    export = load_user_settings().export_dir.strip()
    if export:
        roots.append(Path(export).expanduser().resolve())
    path = Path(body.path).resolve() if body.path else data / "downloads"
    if not any(path.is_relative_to(r) for r in roots):
        raise HTTPException(403, "Caminho fora da pasta de dados/exportação")
    folder = path if path.is_dir() else path.parent
    if not folder.exists():
        raise HTTPException(404, "Pasta não existe")
    opener = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
    try:
        subprocess.Popen([*opener, str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HTTPException(500, f"Não foi possível abrir a pasta: {e}") from e
    return {"ok": True, "folder": str(folder)}



WHISPER_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3", "turbo"]


@router.get("/whisper-models")
def whisper_models() -> dict:
    return {"models": WHISPER_MODELS}


@router.get("/ollama/models")
def ollama_models(url: str | None = None) -> dict:
    import httpx

    base = (url or load_user_settings().ollama_url).rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama não respondeu em {base}: {e or type(e).__name__}") from e
    return {"models": [{"name": m.get("name", ""), "size": m.get("size", 0)} for m in r.json().get("models", [])]}


@router.post("/ollama/test")
def ollama_test(body: OllamaTest) -> dict:
    """Pergunta algo trivial ao modelo e mede o tempo (inclui carregar o modelo na memória)."""
    import time

    import httpx

    base = body.url.rstrip("/")
    t0 = time.monotonic()
    try:
        r = httpx.post(f"{base}/api/chat", timeout=180, json={
            "model": body.model, "stream": False, "options": {"temperature": 0, "num_predict": 20},
            "messages": [{"role": "user", "content": "Responda apenas com a palavra: funcionando"}]})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama não respondeu em {base}: {e or type(e).__name__}") from e
    if r.status_code == 404:
        raise HTTPException(404, f"Modelo {body.model} não está instalado. Rode: ollama pull {body.model}")
    if r.status_code >= 400:
        raise HTTPException(502, f"Ollama devolveu erro {r.status_code}: {r.text[:300]}")
    reply = r.json().get("message", {}).get("content", "").strip()
    return {"ok": True, "reply": reply[:200], "seconds": round(time.monotonic() - t0, 1)}


@router.get("/storage")
def storage(proxy_days: int = 30) -> dict:
    from sqlmodel import Session

    from ..db import engine
    from ..storage import report

    with Session(engine) as s:
        return report(s, proxy_days)


@router.post("/cleanup")
def cleanup(body: CleanupRequest) -> dict:
    from sqlmodel import Session, select

    from ..db import engine
    from ..models import Job
    from ..storage import cleanup as do_cleanup

    with Session(engine) as s:
        if s.exec(select(Job).where(Job.status == "running")).first():
            raise HTTPException(409, "Há tarefas em andamento na Fila; espere terminarem para limpar.")
        return do_cleanup(s, body.temp, body.audio, body.proxies, body.proxy_days)
