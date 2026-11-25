#!/usr/bin/env bash
# Sugere os modelos de IA (Whisper e Ollama) que cabem no seu computador.
#   scripts/sugerir-modelos.sh             só mostra a sugestão
#   scripts/sugerir-modelos.sh --aplicar   salva no app e oferece baixar o modelo
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif command -v python3 >/dev/null; then PY=python3
else echo "Precisa do Python 3. Rode primeiro: scripts/setup.sh"; exit 1; fi
exec "$PY" scripts/sugerir_modelos.py "$@"
