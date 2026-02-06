# 📊 Análise Completa do Projeto ACE-Step V1.5

## 📋 Sumário Executivo

Este documento contém a análise completa do projeto ACE-Step V1.5 para geração de música com IA,
incluindo as modificações realizadas para limitar o uso de memória RAM a 4GB.

---

## 🏗️ Estrutura do Projeto

```
ACE-Step-1.5/
├── acestep/                         # Módulo principal
│   ├── acestep_v15_pipeline.py     # Pipeline Gradio (UI web)
│   ├── api_server.py               # Servidor FastAPI (REST API)
│   ├── handler.py                  # Handler do modelo DiT
│   ├── llm_inference.py            # Handler do LM (5Hz)
│   ├── inference.py                # API de inferência unificada
│   ├── gpu_config.py               # Configuração GPU/memória
│   ├── memory_manager.py           # 🆕 Gerenciador de memória (4GB)
│   ├── gradio_ui/                  # Interface Gradio
│   │   ├── interfaces/             # Componentes de UI
│   │   ├── events/                 # Handlers de eventos
│   │   └── i18n/                   # Traduções
│   └── ...
├── checkpoints/                    # Modelos baixados
├── .env                            # 🆕 Configuração de memória
├── .env.example                    # Template original
├── start_4gb_mode.sh               # 🆕 Script de inicialização
└── ANALISE_PROJETO.md              # 🆕 Este documento
```

---

## 🧠 Componentes de Memória

### Modelos e Consumo de VRAM

| Modelo | VRAM Necessária | Função |
|--------|-----------------|--------|
| **DiT (acestep-v15-turbo)** | ~3-4 GB | Modelo de difusão para geração |
| **VAE** | ~1-2 GB | Codificador/decodificador de áudio |
| **LM 0.6B** | ~3 GB | Language Model pequeno |
| **LM 1.7B** | ~8 GB | Language Model médio |
| **LM 4B** | ~12 GB | Language Model grande |
| **Text Encoder** | ~0.5 GB | Codificador de texto |

### Consumo por Operação

| Operação | VRAM Estimada | RAM Estimada |
|----------|---------------|--------------|
| Geração simples (sem LM) | 3-4 GB | 2-3 GB |
| Geração com LM 0.6B | 6-7 GB | 4-5 GB |
| Geração com LM 1.7B | 11-12 GB | 6-8 GB |
| Batch de 2 amostras | 2x o normal | 1.5x o normal |

---

## ⚙️ Sistema de Tiers de Memória

O projeto usa um sistema de "tiers" baseado na VRAM disponível:

### Tier 1 (≤4GB) - **CONFIGURADO PARA VOCÊ**
- ✅ Duração máxima: 180s (3 minutos)
- ✅ Batch size: 1 (sem batching)
- ✅ LM: Desabilitado
- ✅ Offload para CPU: Habilitado

### Tier 2 (4-6GB)
- Duração máxima: 360s (6 minutos)
- Batch size: 1
- LM: Desabilitado

### Tier 3 (6-8GB)
- Duração máxima: 240s (4 minutos) com LM / 360s sem LM
- Batch size: 1-2
- LM: 0.6B opcional

### Tier 4+ (>8GB)
- Durações e batch sizes maiores
- LM: 0.6B, 1.7B, 4B disponíveis

---

## 🛠️ Modificações Realizadas

### 1. Arquivo `.env` (Configuração Principal)

```bash
# Forçar limite de 4GB
MAX_CUDA_VRAM=4

# Desabilitar LM por padrão (economiza ~3GB)
ACESTEP_INIT_LM_DEFAULT=false

# Offload para CPU
ACESTEP_OFFLOAD_TO_CPU=true
ACESTEP_OFFLOAD_DIT_TO_CPU=true

# Limites de geração
ACESTEP_MAX_DURATION=180
ACESTEP_MAX_BATCH_SIZE=1

# PyTorch memory management
PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.6,max_split_size_mb:128
```

### 2. Módulo `memory_manager.py` (Novo)

Funcionalidades:
- **Monitoramento de memória** em tempo real
- **Validação de parâmetros** antes da geração
- **Garbage collection forçado** após cada geração
- **Sincronização** entre servidor local e web
- **Decorator** para aplicar limites automaticamente

### 3. Script `start_4gb_mode.sh` (Novo)

Menu interativo para:
1. Iniciar Gradio UI (porta 7860)
2. Iniciar API Server (porta 8001)
3. Iniciar ambos os serviços
4. Testar configuração de memória

---

## 🔄 Sincronização Local ↔ Web

A sincronização garante que os mesmos limites sejam aplicados:

```
┌─────────────────────┐      ┌─────────────────────┐
│   SERVIDOR LOCAL    │      │     VERSÃO WEB      │
├─────────────────────┤      ├─────────────────────┤
│ .env carregado      │←────→│ .env carregado      │
│ memory_manager.py   │      │ memory_manager.py   │
│ gpu_config.py       │      │ gpu_config.py       │
└─────────────────────┘      └─────────────────────┘
           │                            │
           └──────────┬─────────────────┘
                      ▼
         ┌─────────────────────────┐
         │   MESMOS LIMITES:       │
         │   - Max 4GB VRAM        │
         │   - Max 180s duração    │
         │   - Batch size: 1       │
         │   - LM: Desabilitado    │
         └─────────────────────────┘
```

### Mecanismo de Sincronização

1. **Variáveis de Ambiente**: Ambos os modos leem as mesmas variáveis `.env`
2. **GPUConfig Global**: O objeto `GPUConfig` é compartilhado
3. **MemoryManager Singleton**: Uma única instância gerencia todos os limites
4. **Validação de Parâmetros**: Ambos validam com `validate_generation_params()`

---

## 🚀 Como Usar

### Opção 1: Script Interativo (Recomendado)

```bash
cd "/home/layton/Área de trabalho/ACE 1.5"
./start_4gb_mode.sh
```

### Opção 2: Gradio UI Direto

```bash
cd "/home/layton/Área de trabalho/ACE 1.5"
source .venv/bin/activate  # Se usar venv

python -m acestep.acestep_v15_pipeline \
    --server-name 0.0.0.0 \
    --port 7860 \
    --init_service true \
    --offload_to_cpu true \
    --language pt
```

### Opção 3: API Server

```bash
cd "/home/layton/Área de trabalho/ACE 1.5"
source .venv/bin/activate

python -m uvicorn acestep.api_server:app \
    --host 0.0.0.0 \
    --port 8001 \
    --workers 1
```

---

## 📈 Otimizações de Memória Aplicadas

### 1. Offload para CPU
Quando um modelo não está em uso, ele é movido para RAM:
- DiT → CPU após geração
- VAE → CPU após decodificação
- Text Encoder → CPU após encoding

### 2. Garbage Collection Agressivo
```python
# Após cada geração:
gc.collect()
torch.cuda.empty_cache()
torch.cuda.synchronize()
```

### 3. Limites de Alocação PyTorch
```bash
PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.6,max_split_size_mb:128
```

### 4. Desabilitação do LM
O Language Model (5Hz LM) consome ~3GB adicionais. Com 4GB, não é viável.

### 5. Geração Tiled (Tile-based)
Decodificação VAE em chunks para economizar memória:
```python
use_tiled_decode=True  # Padrão habilitado
```

---

## ⚠️ Limitações do Modo 4GB

| Funcionalidade | Status | Motivo |
|----------------|--------|--------|
| Geração básica de música | ✅ Funciona | DiT + VAE cabem |
| Letras customizadas | ✅ Funciona | Texto simples |
| Language Model (thinking=true) | ❌ Desabilitado | +3GB necessários |
| Batch >1 amostra | ❌ Desabilitado | Memória insuficiente |
| Durações >3 min | ❌ Limitado | Risco de OOM |
| Audio Cover/Remix | ✅ Funciona | Usa mesma memória |
| Multi-modelo | ❌ Limitado | Apenas 1 modelo por vez |

---

## 🔧 Troubleshooting

### Erro: CUDA Out of Memory

```bash
# 1. Verificar uso atual
nvidia-smi

# 2. Matar processos que usam GPU
fuser -k /dev/nvidia*

# 3. Reiniciar o servidor
./start_4gb_mode.sh
```

### Erro: Servidor lento

```bash
# Verificar se offload está ativo
grep OFFLOAD .env
# Deve mostrar:
# ACESTEP_OFFLOAD_TO_CPU=true
```

### Mudar para modo mais leve

```bash
# Editar .env
nano .env

# Reduzir duração máxima
ACESTEP_MAX_DURATION=120  # 2 minutos
```

---

## 📊 Monitoramento

### Via Python

```python
from acestep.memory_manager import get_memory_manager

manager = get_memory_manager()
status = manager.get_status()
print(status)
```

### Via Terminal

```bash
# GPU
watch -n 1 nvidia-smi

# RAM
watch -n 1 "free -h"
```

---

## 📝 Próximos Passos Sugeridos

1. **Quantização de Modelos**: Converter para INT8 para reduzir VRAM
2. **Model Sharding**: Dividir modelo entre CPU e GPU
3. **Caching de Resultados**: Evitar recomputação
4. **Compressão de Áudio**: Gerar em qualidade menor primeiro

---

*Documento gerado em: 04/02/2026*
*Configuração: ACE-Step V1.5 com limite de 4GB RAM*
