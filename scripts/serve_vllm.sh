#!/usr/bin/env bash
set -euo pipefail
: "${MODEL_PATH:?Set MODEL_PATH to the base model or merged adapter checkpoint}"
vllm serve "$MODEL_PATH" --host 127.0.0.1 --port "${PORT:-8000}" \
  --enable-prefix-caching --max-model-len 16384 "$@"
