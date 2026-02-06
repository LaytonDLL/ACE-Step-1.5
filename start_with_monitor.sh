#!/bin/bash
# ================================================================================
# ACE-Step - Iniciar com Monitoramento de Memória em Tempo Real
# ================================================================================
# Este script inicia o logger de memória e depois o servidor
# O log é salvo em: logs/memory_realtime.log
# ================================================================================

set -euo pipefail

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Criar diretório de logs
mkdir -p logs

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     ACE-Step - Inicialização com Monitoramento              ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Limpar log anterior
LOG_FILE="logs/memory_realtime.log"
if [ -f "$LOG_FILE" ]; then
    mv "$LOG_FILE" "logs/memory_realtime_$(date +%Y%m%d_%H%M%S).log.bak"
    echo -e "${YELLOW}Log anterior arquivado${NC}"
fi

# Iniciar logger em background
echo -e "${CYAN}[1/2] Iniciando logger de memória em background...${NC}"
python3 scripts/realtime_memory_logger.py > /dev/null 2>&1 &
LOGGER_PID=$!
echo -e "${GREEN}       Logger iniciado (PID: $LOGGER_PID)${NC}"
echo ""

# Função para matar o logger ao sair
cleanup() {
    echo ""
    echo -e "${YELLOW}Encerrando logger de memória...${NC}"
    kill $LOGGER_PID 2>/dev/null || true
    echo -e "${GREEN}✅ Logs salvos em: $LOG_FILE${NC}"
}
trap cleanup EXIT

# Mostrar status inicial
echo -e "${CYAN}[2/2] Status inicial do sistema:${NC}"
echo -e "       RAM Disponível: $(grep MemAvailable /proc/meminfo | awk '{printf "%.1f GB", $2/1024/1024}')"
echo -e "       GPU VRAM Livre: $(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | awk '{printf "%.1f GB", $1/1024}')"
echo ""

# Esperar um pouco para o logger começar
sleep 1

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Iniciando servidor ACE-Step...                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}📋 O log de memória está sendo gravado em: ${LOG_FILE}${NC}"
echo -e "${YELLOW}📋 Para ver em tempo real em outro terminal: tail -f ${LOG_FILE}${NC}"
echo ""

# Iniciar o servidor (Opção 1 = Gradio UI)
echo "1" | ./start_4gb_mode.sh
