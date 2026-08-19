#!/usr/bin/env bash
# Serve an open HF model behind an OpenAI-compatible endpoint, then point the
# agent at it with DA_MODEL_BACKEND=openai_compatible.
set -euo pipefail

MODEL="${DA_MODEL_ID:-Qwen/Qwen2.5-7B-Instruct}"
PORT="${PORT:-8001}"

# --- Option A: vLLM (recommended for GPUs) -----------------------------------
#   pip install vllm
vllm serve "$MODEL" --port "$PORT"

# --- Option B: HF Text Generation Inference (Docker) -------------------------
# docker run --gpus all -p "${PORT}:80" \
#   -v "$HOME/.cache/huggingface:/data" \
#   ghcr.io/huggingface/text-generation-inference:latest \
#   --model-id "$MODEL"
