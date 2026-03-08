#!/usr/bin/env bash

llama-server \
  -hf Qwen/Qwen2.5-7B-Instruct-GGUF:Q4_K_M
  --port 8080 \
  --host 127.0.0.1 \
  --ctx-size 32768 \
  --n-gpu-layers 35 \
  --flash-attn \
  --temperature 0.1 \
  --top-p 0.1 \
  --repeat-penalty 1.1 \
  --verbose
