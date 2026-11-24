#!/usr/bin/env bash
# Instala a Máquina de Cortes: ferramentas que faltarem, ambiente Python, interface e modelos de IA.
#
#   scripts/setup.sh                 instala tudo (inclui ~8 GB de modelos de IA na primeira vez)
#   scripts/setup.sh --sem-modelos   pula o download dos modelos (baixa depois, no primeiro uso)
#
# No Linux (x86_64), o que faltar é instalado SEM sudo, só na sua pasta pessoal (~/.local):
# uv (Python), FFmpeg (com legendas e NVENC), Node.js e Ollama.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
LOCAL="$HOME/.local"
export PATH="$LOCAL/bin:$PATH"

WITH_MODELS=1
for a in "$@"; do
  case "$a" in
    --sem-modelos) WITH_MODELS=0 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
  esac
done

if [ -t 1 ]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[1m'; N=$'\e[0m'; else G= Y= R= B= N=; fi
step() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$1"; }
die()  { printf '  %s✗ %s%s\n' "$R" "$1" "$N"; exit 1; }

OS="$(uname -s)"; ARCH="$(uname -m)"
AUTO_INSTALL=0
[ "$OS" = Linux ] && [ "$ARCH" = x86_64 ] && AUTO_INSTALL=1
mkdir -p "$LOCAL/bin" "$LOCAL/opt"

download() {  # download URL DESTINO (barra de progresso só no terminal)
  if [ -t 1 ]; then curl -fL --retry 3 --progress-bar -o "$2" "$1"; else curl -fsSL --retry 3 -o "$2" "$1"; fi
}

# ---------------------------------------------------------------------------
step "1/5 Ferramentas"
command -v curl >/dev/null || die "Precisa do curl. Ubuntu: sudo apt install curl"

# uv (gerencia o Python 3.12 do projeto)
if ! command -v uv >/dev/null; then
  echo "  → instalando uv (gerenciador de Python)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  command -v uv >/dev/null || die "Não consegui instalar o uv. Veja https://docs.astral.sh/uv/"
fi
ok "uv $(uv --version | awk '{print $2}')"

# FFmpeg (precisa do filtro 'ass' para legendas)
has_libass() { ffmpeg -hide_banner -filters 2>/dev/null | awk '$2 == "ass" { found = 1 } END { exit !found }'; }
if ! command -v ffmpeg >/dev/null || ! has_libass; then
  if [ "$AUTO_INSTALL" = 1 ]; then
    echo "  → baixando FFmpeg (build estático com libass e NVENC, ~100 MB)…"
    tmp="$(mktemp -d)"
    download "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz" "$tmp/ffmpeg.tar.xz"
    tar -xJf "$tmp/ffmpeg.tar.xz" -C "$LOCAL/opt"
    rm -rf "$tmp"
    ln -sf "$LOCAL/opt/ffmpeg-n8.1-latest-linux64-gpl-8.1/bin/ffmpeg" "$LOCAL/bin/ffmpeg"
    ln -sf "$LOCAL/opt/ffmpeg-n8.1-latest-linux64-gpl-8.1/bin/ffprobe" "$LOCAL/bin/ffprobe"
    hash -r
  elif [ "$OS" = Darwin ]; then
    die "Instale o FFmpeg: brew install ffmpeg   (e rode este script de novo)"
  else
    die "Instale o FFmpeg com libass (ex.: sudo apt install ffmpeg) e rode de novo."
  fi
fi
has_libass || die "O ffmpeg encontrado não tem o filtro 'ass' (legendas)."
ok "FFmpeg $(ffmpeg -version | head -1 | awk '{print $3}')"

# Node.js 20+ (compila a interface e o yt-dlp usa para o YouTube)
node_ok() { command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]; }
if ! node_ok; then
  if [ "$AUTO_INSTALL" = 1 ]; then
    echo "  → baixando Node.js 22 LTS (~30 MB)…"
    ver="$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep -oE 'node-v22\.[0-9.]+-linux-x64\.tar\.xz' | head -1)"
    [ -n "$ver" ] || die "Não achei a versão do Node.js para baixar."
    tmp="$(mktemp -d)"
    download "https://nodejs.org/dist/latest-v22.x/$ver" "$tmp/node.tar.xz"
    rm -rf "$LOCAL/opt/node"
    mkdir -p "$LOCAL/opt/node"
    tar -xJf "$tmp/node.tar.xz" -C "$LOCAL/opt/node" --strip-components=1
    rm -rf "$tmp"
    for b in node npm npx; do ln -sf "$LOCAL/opt/node/bin/$b" "$LOCAL/bin/$b"; done
    hash -r
  elif [ "$OS" = Darwin ]; then
    die "Instale o Node.js 20+: brew install node   (e rode este script de novo)"
  else
    die "Instale o Node.js 20 ou mais novo: https://nodejs.org"
  fi
fi
ok "Node.js $(node --version)"

# Ollama (IA local que escolhe os trechos)
if ! command -v ollama >/dev/null; then
  if [ "$AUTO_INSTALL" = 1 ]; then
    command -v zstd >/dev/null || die "Precisa do zstd para descompactar o Ollama: sudo apt install zstd"
    echo "  → baixando Ollama (~1,5 GB com as libs de GPU)…"
    tmp="$(mktemp -d)"
    download "https://ollama.com/download/ollama-linux-amd64.tar.zst" "$tmp/ollama.tar.zst"
    rm -rf "$LOCAL/opt/ollama"
    mkdir -p "$LOCAL/opt/ollama"
    zstd -dc "$tmp/ollama.tar.zst" | tar -x -C "$LOCAL/opt/ollama"
    rm -rf "$tmp"
    ln -sf "$LOCAL/opt/ollama/bin/ollama" "$LOCAL/bin/ollama"
    hash -r
  elif [ "$OS" = Darwin ]; then
    warn "Ollama não encontrado. Instale em https://ollama.com/download e rode este script de novo."
  else
    warn "Ollama não encontrado. Instale: curl -fsSL https://ollama.com/install.sh | sh"
  fi
fi
command -v ollama >/dev/null && ok "Ollama $(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"

if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  ok "GPU NVIDIA: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
else
  warn "Sem GPU NVIDIA (ou driver não instalado): vai funcionar na CPU, só que mais devagar."
fi

# ---------------------------------------------------------------------------
step "2/5 Ambiente Python (.venv)"
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -r backend/requirements.txt
ok "dependências Python instaladas"

# ---------------------------------------------------------------------------
step "3/5 Interface"
(cd frontend && npm ci --no-audit --no-fund && npm run build) >/dev/null
ok "interface compilada (frontend/dist)"

# ---------------------------------------------------------------------------
step "4/5 Modelos de IA"
if [ "$WITH_MODELS" = 1 ]; then
  .venv/bin/python run.py --baixar-modelos || warn "Algum modelo não baixou — dá para tentar de novo depois (o app avisa no Diagnóstico)."
else
  warn "Pulado (--sem-modelos). O Whisper baixa sozinho no primeiro uso; o modelo do Ollama: ollama pull qwen2.5:7b"
fi

# ---------------------------------------------------------------------------
step "5/5 Diagnóstico"
.venv/bin/python run.py --diagnostico || true

printf '\n%sPronto!%s Para abrir o app:  %sscripts/start.sh%s   (abre http://localhost:8000 no navegador)\n' "$G$B" "$N" "$B" "$N"
