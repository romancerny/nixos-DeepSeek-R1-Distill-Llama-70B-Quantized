# Autonomous Selfhosted Trading Multiagent LLM Research/Coding Lab

On ```i7``` laptop (2021) with ```64GB RAM``` & ```RTX 3080 16GB VRAM``` & ```48GB SWAP```

With ```DeepSeek-R1-Distill-Llama-70B-Uncensored-v2-Unbiased-Reasoner.Q5_K_M.gguf``` _researchers_ (via llama.cpp: `llama-cli -m ~/models/DeepSeek-R1-Distill-Llama-70B-Uncensored-v2-Unbiased-Reasoner.Q5_K_M.gguf -ngl 23 -c 16384 -ctk q8_0 -ctv q8_0`) and ```qwen2.5-coder:32b``` _coders_ (via Ollama; ```deepseek-r1:70b``` also remains available via Ollama)

## How To

### 1. System Install

Install a brand new system on a empty disk guide: [NixOS-ai-system-setup-guide.md](docs/NixOS-ai-system-setup-guide.md)

### 2. LLM Model Selection

Reasoning [agentic-ai-setup-research.md](docs/agentic-ai-setup-research.md)
