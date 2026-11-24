"""Inicia API (uvicorn) + worker juntos. Uso: python run.py [--dev] [--no-browser]

--dev             : também sobe o Vite (frontend com hot reload em http://localhost:5173, proxy /api → 8000).
--baixar-modelos  : baixa o Whisper e o modelo do Ollama adequados ao hardware e sai.
--diagnostico     : mostra o diagnóstico (ffmpeg, Ollama, GPU…) e sai.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def build_env() -> dict[str, str]:
    """PATH com ~/.local/bin (ffmpeg/ollama instalados no usuário) e libs CUDA dos pacotes pip nvidia-*."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    local_bin = Path.home() / ".local" / "bin"
    env["PATH"] = os.pathsep.join([str(local_bin), env.get("PATH", "")])
    if sys.platform == "win32":
        # Windows: as DLLs do CUDA (pip nvidia-*) ficam em Lib/site-packages/nvidia/*/bin e precisam estar no PATH
        dll_dirs = [str(d) for d in sorted(Path(sys.prefix).glob("Lib/site-packages/nvidia/*/bin")) if d.is_dir()]
        env["PATH"] = os.pathsep.join([*dll_dirs, env["PATH"]])
        return env
    nvidia_libs = [str(d) for d in sorted(Path(sys.prefix).glob("lib/python3*/site-packages/nvidia/*/lib")) if d.is_dir()]
    if nvidia_libs:
        env["LD_LIBRARY_PATH"] = os.pathsep.join([*nvidia_libs, env.get("LD_LIBRARY_PATH", "")]).rstrip(os.pathsep)
    return env


def ensure_ollama(env: dict[str, str]) -> subprocess.Popen | None:
    """Sobe `ollama serve` se não estiver respondendo e o binário existir."""
    url = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
    try:
        urllib.request.urlopen(f"{url}/api/version", timeout=1)
        return None  # já está rodando
    except OSError:
        pass
    exe = shutil.which("ollama", path=env["PATH"])
    if not exe:
        print("⚠ Ollama não encontrado — a análise com IA não vai funcionar.")
        return None
    log = (ROOT / "data" / "logs")
    log.mkdir(parents=True, exist_ok=True)
    print("→ iniciando ollama serve")
    return subprocess.Popen([exe, "serve"], env=env, stdout=open(log / "ollama.log", "ab"), stderr=subprocess.STDOUT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="sobe também o Vite dev server")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--baixar-modelos", action="store_true", help="baixa Whisper + modelo do Ollama e sai")
    ap.add_argument("--diagnostico", action="store_true", help="mostra o diagnóstico do sistema e sai")
    args = ap.parse_args()

    if args.baixar_modelos or args.diagnostico:
        env = build_env()
        ollama = ensure_ollama(env)
        if ollama:
            for _ in range(40):  # espera o Ollama subir
                try:
                    urllib.request.urlopen(os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434") + "/api/version", timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
        try:
            cmd = [sys.executable, "-m", "app.prefetch", *(["--check"] if args.diagnostico else [])]
            return subprocess.call(cmd, cwd=BACKEND, env=env)
        finally:
            if ollama and ollama.poll() is None:
                ollama.terminate()

    host = os.environ.get("MDC_HOST", "127.0.0.1")
    port = os.environ.get("MDC_PORT", "8000")
    py = sys.executable
    env = build_env()

    import socket

    with socket.socket() as sock:
        if sock.connect_ex((host, int(port))) == 0:
            print(f"✗ A porta {port} já está em uso — o app já está aberto em outra janela?\n"
                  f"  Abra http://localhost:{port} ou use outra porta:  MDC_PORT={int(port) + 1} scripts/start.sh",
                  file=sys.stderr)
            return 1

    procs: list[subprocess.Popen] = []
    ollama = ensure_ollama(env)
    # SSE mantém conexões abertas: sem limite, o desligamento gracioso esperaria o navegador fechar
    api_cmd = [py, "-m", "uvicorn", "app.main:app", "--host", host, "--port", port, "--timeout-graceful-shutdown", "3"]
    if args.dev:
        api_cmd += ["--reload", "--reload-dir", "app"]
    procs.append(subprocess.Popen(api_cmd, cwd=BACKEND, env=env))
    procs.append(subprocess.Popen([py, "-m", "app.worker.runner"], cwd=BACKEND, env=env))

    url = f"http://localhost:{port}"
    if args.dev:
        npm = shutil.which("npm")
        if not npm:
            print("npm não encontrado — rode sem --dev", file=sys.stderr)
        else:
            procs.append(subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND, env=env))
            url = "http://localhost:5173"
    elif not (FRONTEND / "dist" / "index.html").exists():
        print("⚠ frontend/dist não existe. Rode scripts/setup.sh (ou: cd frontend && npm run build).")

    print(f"\n  Máquina de Cortes → {url}\n", flush=True)
    if not args.no_browser:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()

    def shutdown(*_a) -> None:
        if ollama and ollama.poll() is None:
            procs.append(ollama)  # só encerra o Ollama se fomos nós que subimos
        for p in procs:
            if p.poll() is None:
                p.terminate()
        deadline = time.time() + 5
        for p in procs:
            try:
                p.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()

    signal.signal(signal.SIGTERM, lambda *a: (shutdown(), sys.exit(0)))
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("Um dos processos terminou; encerrando os demais.", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
