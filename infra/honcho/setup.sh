#!/usr/bin/env bash
# Bring up self-hosted Honcho with local EmbeddingGemma embeddings and connect it to Hermes.
# Requirements: docker compose, ollama, hermes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${HONCHO_DIR:-$HOME/.local/share/honcho}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "[1/5] Ollama model embeddinggemma"
ollama pull embeddinggemma
curl -fsS http://localhost:11434/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"embeddinggemma","input":["ping"]}' \
  | python3 -c 'import sys,json; d=json.load(sys.stdin)["data"][0]["embedding"]; print("  dim =", len(d)); assert len(d)==768'

echo "[2/5] Honcho source -> $DEST"
if [ ! -d "$DEST/.git" ]; then
  git clone --depth 1 https://github.com/plastic-labs/honcho.git "$DEST"
fi
cp -n "$DEST/docker-compose.yml.example" "$DEST/docker-compose.yml" || true
cp "$HERE/docker-compose.override.yml" "$DEST/docker-compose.override.yml"
if [ ! -f "$DEST/.env" ]; then
  cp "$HERE/.env.example" "$DEST/.env"
  echo "  !! Fill in the LLM key in $DEST/.env (LLM_GEMINI_API_KEY or a local LLM) and run again."
  exit 1
fi

echo "[3/5] docker compose up"
(cd "$DEST" && docker compose up -d --build)
for _ in $(seq 1 60); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/health >/dev/null && echo "  honcho: healthy"

echo "[4/5] Hermes <- Honcho"
hermes plugins install honcho || true
if [ ! -f "$HERMES_HOME/honcho.json" ]; then
  cp "$HERE/honcho.json.example" "$HERMES_HOME/honcho.json"
fi
hermes config set memory.provider honcho

echo "[5/5] Check"
hermes memory status || true
hermes honcho status || true
