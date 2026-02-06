#!/usr/bin/env bash
# ================================================================================
# ACE-Step V1.5 - OpenRouter API Server (Memory Limited Mode)
# ================================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# 1. Carregar variáveis de ambiente
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

# 2. Forçar limites de memória
export ACESTEP_MEMORY_LIMIT_GB="${ACESTEP_MEMORY_LIMIT_GB:-4}"
export MAX_CUDA_VRAM="${MAX_CUDA_VRAM:-4}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-garbage_collection_threshold:0.6,max_split_size_mb:128}"
export TOKENIZERS_PARALLELISM="false"

# 3. Ativar ambiente virtual
if [ -d "$ROOT_DIR/.venv" ]; then
    source "$ROOT_DIR/.venv/bin/activate"
elif [ -d "$ROOT_DIR/venv" ]; then
    source "$ROOT_DIR/venv/bin/activate"
fi

HOST="${ACESTEP_API_HOST:-0.0.0.0}"
PORT="8002"
LOG_LEVEL="${ACESTEP_API_LOG_LEVEL:-info}"

echo "Iniciando OpenRouter API em http://$HOST:$PORT..."

nohup python3 -m uvicorn openrouter.openrouter_api_server:app \
	--host "$HOST" \
	--port "$PORT" \
	--workers 1 \
	--log-level "$LOG_LEVEL" > openrouter.log 2>&1 &

echo "Servidor iniciado em background (PID $!). Logs em openrouter.log"