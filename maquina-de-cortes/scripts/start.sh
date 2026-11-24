#!/usr/bin/env bash
# Abre a Máquina de Cortes (API + worker + Ollama) em http://localhost:8000. Ctrl+C para fechar.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
if [ ! -x .venv/bin/python ]; then
  echo "A instalação ainda não foi feita. Rode primeiro:  scripts/setup.sh"
  exit 1
fi
exec .venv/bin/python run.py "$@"
