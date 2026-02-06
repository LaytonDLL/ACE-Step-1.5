#!/usr/bin/env bash
# ================================================================================
# ACE-Step V1.5 - Script de Inicialização com Limite de 4GB RAM
# ================================================================================
# Este script inicia o servidor local com todas as otimizações de memória
# Sincronizado com a versão web para garantir consistência
# ================================================================================

set -euo pipefail

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Diretório do projeto
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       ACE-Step V1.5 - Modo Memória Limitada (4GB)          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo

# ================================================================================
# Verificar memória do sistema
# ================================================================================
echo -e "${BLUE}[INFO]${NC} Verificando memória do sistema..."

# Memória RAM total
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_GB=$(echo "scale=2; $TOTAL_RAM_KB / 1024 / 1024" | bc)
echo -e "${GREEN}  ✓${NC} RAM Total: ${TOTAL_RAM_GB}GB"

# Memória RAM disponível
AVAIL_RAM_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
AVAIL_RAM_GB=$(echo "scale=2; $AVAIL_RAM_KB / 1024 / 1024" | bc)
echo -e "${GREEN}  ✓${NC} RAM Disponível: ${AVAIL_RAM_GB}GB"

# GPU VRAM (se disponível)
if command -v nvidia-smi &> /dev/null; then
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    GPU_MEM_GB=$(echo "scale=2; $GPU_MEM / 1024" | bc 2>/dev/null || echo "0")
    echo -e "${GREEN}  ✓${NC} GPU VRAM Total: ${GPU_MEM_GB}GB"
else
    echo -e "${YELLOW}  ⚠${NC} NVIDIA GPU não detectada - rodando em modo CPU"
    GPU_MEM_GB="0"
fi

echo

# ================================================================================
# Carregar variáveis de ambiente
# ================================================================================
echo -e "${BLUE}[INFO]${NC} Carregando configurações de memória..."

if [ -f "$ROOT_DIR/.env" ]; then
    echo -e "${GREEN}  ✓${NC} Arquivo .env encontrado"
    set -a
    source "$ROOT_DIR/.env"
    set +a
else
    echo -e "${YELLOW}  ⚠${NC} Arquivo .env não encontrado, usando defaults"
fi

# Forçar limite de 4GB
export MAX_CUDA_VRAM="${MAX_CUDA_VRAM:-4}"
export ACESTEP_MEMORY_LIMIT_GB="4"
export ACESTEP_OFFLOAD_TO_CPU="${ACESTEP_OFFLOAD_TO_CPU:-true}"
export ACESTEP_OFFLOAD_DIT_TO_CPU="${ACESTEP_OFFLOAD_DIT_TO_CPU:-true}"
export ACESTEP_INIT_LM_DEFAULT="${ACESTEP_INIT_LM_DEFAULT:-false}"
export ACESTEP_MAX_DURATION="${ACESTEP_MAX_DURATION:-180}"
export ACESTEP_MAX_BATCH_SIZE="${ACESTEP_MAX_BATCH_SIZE:-1}"

# PyTorch memory management
export PYTORCH_CUDA_ALLOC_CONF="garbage_collection_threshold:0.6,max_split_size_mb:128"
export TOKENIZERS_PARALLELISM="false"

# Limpar proxies que podem afetar o Gradio
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY 2>/dev/null || true

echo -e "${GREEN}  ✓${NC} Limite de memória: ${MAX_CUDA_VRAM}GB"
echo -e "${GREEN}  ✓${NC} Offload para CPU: ${ACESTEP_OFFLOAD_TO_CPU}"
echo -e "${GREEN}  ✓${NC} LM desabilitado por padrão: $([ "$ACESTEP_INIT_LM_DEFAULT" = "false" ] && echo "Sim" || echo "Não")"
echo -e "${GREEN}  ✓${NC} Duração máxima: ${ACESTEP_MAX_DURATION}s ($(( ACESTEP_MAX_DURATION / 60 )) min)"
echo -e "${GREEN}  ✓${NC} Batch size máximo: ${ACESTEP_MAX_BATCH_SIZE}"
echo

# ================================================================================
# Verificar ambiente Python
# ================================================================================
echo -e "${BLUE}[INFO]${NC} Verificando ambiente Python..."

# Tentar ativar venv se existir
if [ -d "$ROOT_DIR/.venv" ]; then
    echo -e "${GREEN}  ✓${NC} Ativando ambiente virtual .venv"
    source "$ROOT_DIR/.venv/bin/activate"
elif [ -d "$ROOT_DIR/venv" ]; then
    echo -e "${GREEN}  ✓${NC} Ativando ambiente virtual venv"
    source "$ROOT_DIR/venv/bin/activate"
else
    echo -e "${YELLOW}  ⚠${NC} Nenhum ambiente virtual encontrado, usando Python do sistema"
fi

# Verificar Python
PYTHON_VERSION=$(python3 --version 2>&1 || python --version 2>&1 || echo "não encontrado")
echo -e "${GREEN}  ✓${NC} Python: $PYTHON_VERSION"
echo

# ================================================================================
# Selecionar modo de execução
# ================================================================================
echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║              Selecione o modo de execução:                  ║${NC}"
echo -e "${CYAN}╠════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║  ${NC}1) ${GREEN}Gradio UI${NC} - Interface web completa (localhost:7860)     ${CYAN}║${NC}"
echo -e "${CYAN}║  ${NC}2) ${GREEN}API Server${NC} - Servidor REST API (localhost:8001)        ${CYAN}║${NC}"
echo -e "${CYAN}║  ${NC}3) ${GREEN}Gradio + API${NC} - Ambos os serviços                       ${CYAN}║${NC}"
echo -e "${CYAN}║  ${NC}4) ${GREEN}Verificar memória${NC} - Apenas teste de configuração       ${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
echo

read -p "Escolha uma opção [1-4]: " CHOICE

case $CHOICE in
    1)
        echo
        echo -e "${BLUE}[INFO]${NC} Iniciando Gradio UI com segurança..."
        echo -e "${GREEN}  ✓${NC} Autenticação: ${ACESTEP_AUTH_USERNAME:-admin}"
        echo -e "${YELLOW}[WARN]${NC} Pressione Ctrl+C para parar o servidor"
        echo
        
        # Verificar se autenticação está habilitada
        AUTH_ARGS=""
        if [ "${ACESTEP_AUTH_ENABLED:-true}" = "true" ]; then
            AUTH_ARGS="--auth-username ${ACESTEP_AUTH_USERNAME:-admin} --auth-password ${ACESTEP_AUTH_PASSWORD:-music2026}"
            echo -e "${GREEN}  🔒 Autenticação habilitada${NC}"
        fi
        
        python3 -m acestep.acestep_v15_pipeline \
            --server-name 0.0.0.0 \
            --port 7860 \
            --init_service true \
            --init_llm true \
            --lm_model_path "${ACESTEP_LM_MODEL_PATH:-acestep-5Hz-lm-1.7B}" \
            --backend "${ACESTEP_LM_BACKEND:-vllm}" \
            --offload_to_cpu "${ACESTEP_OFFLOAD_TO_CPU:-true}" \
            --config_path "${ACESTEP_CONFIG_PATH:-acestep-v15-turbo}" \
            --language pt \
            $AUTH_ARGS
        ;;
    
    2)
        echo
        echo -e "${BLUE}[INFO]${NC} Iniciando API Server com limite de 4GB..."
        echo -e "${YELLOW}[WARN]${NC} Pressione Ctrl+C para parar o servidor"
        echo
        
        python3 -m uvicorn acestep.api_server:app \
            --host "${ACESTEP_API_HOST:-0.0.0.0}" \
            --port "${ACESTEP_API_PORT:-8001}" \
            --workers 1 \
            --log-level "${ACESTEP_API_LOG_LEVEL:-info}"
        ;;
    
    3)
        echo
        echo -e "${BLUE}[INFO]${NC} Iniciando Gradio UI + API endpoints..."
        echo -e "${YELLOW}[WARN]${NC} Pressione Ctrl+C para parar o servidor"
        echo
        
        python3 -m acestep.acestep_v15_pipeline \
            --server-name 0.0.0.0 \
            --port 7860 \
            --init_service true \
            --enable-api \
            --offload_to_cpu true \
            --offload_dit_to_cpu true \
            --config_path "${ACESTEP_CONFIG_PATH:-acestep-v15-turbo}" \
            --language pt
        ;;
    
    4)
        echo
        echo -e "${BLUE}[INFO]${NC} Testando configuração de memória..."
        echo
        
        python3 -c "
from acestep.memory_manager import get_memory_manager, apply_memory_limits

print('='*60)
print('Teste de Configuração de Memória ACE-Step')
print('='*60)

# Aplicar limites
constraints = apply_memory_limits()

# Obter status
manager = get_memory_manager()
status = manager.get_status()

print()
print('Configuração:')
for key, value in status['config'].items():
    print(f'  {key}: {value}')

print()
print('Uso atual de memória:')
for key, value in status['current_usage'].items():
    print(f'  {key}: {value:.2f} GB')

print()
print('Limites de geração:')
for key, value in status['constraints'].items():
    print(f'  {key}: {value}')

print()
if status['healthy']:
    print('✓ Sistema saudável - pronto para gerar música')
else:
    print('⚠ Atenção: memória baixa - feche outros aplicativos')

print('='*60)
"
        ;;
    
    *)
        echo -e "${RED}[ERRO]${NC} Opção inválida"
        exit 1
        ;;
esac
