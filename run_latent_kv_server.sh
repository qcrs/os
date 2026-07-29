#!/usr/bin/env bash
# Start the real latent KV model server inside SynapseX-wmw71 container.
# Uses GPU1 (53GB free) to avoid conflict with vLLM on GPU0.
#
# Usage:
#   ./run_latent_kv_server.sh            # start in background
#   ./run_latent_kv_server.sh --fg       # foreground (logs to stdout)
#   ./run_latent_kv_server.sh --check    # check if already running
#   ./run_latent_kv_server.sh --stop     # kill the server

set -euo pipefail

CONTAINER="SynapseX-wmw71"
PORT=8101
GPU=1
MODEL_PATH="/data/models/Qwen3-8B"
LOG_FILE="/tmp/latent_kv_server.log"
PROJECT="/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz"

# ── helpers ──────────────────────────────────────────────────────────────────

check_running() {
  docker exec "$CONTAINER" bash -c \
    "curl -s http://localhost:${PORT}/health 2>/dev/null | python3 -c \
     'import sys,json; d=json.load(sys.stdin); print(d[\"status\"])' 2>/dev/null" \
    || true
}

wait_ready() {
  echo -n "Waiting for model server (port $PORT) to become ready"
  for i in $(seq 1 60); do
    status=$(check_running)
    if [ "$status" = "ok" ]; then
      echo " ✓"
      return 0
    fi
    echo -n "."
    sleep 5
  done
  echo " ✗  (timeout after 300s)"
  echo "Logs:"
  docker exec "$CONTAINER" tail -30 "$LOG_FILE" 2>/dev/null || true
  return 1
}

# ── modes ─────────────────────────────────────────────────────────────────────

MODE="${1:-}"

if [ "$MODE" = "--check" ]; then
  status=$(check_running)
  if [ "$status" = "ok" ]; then
    echo "✓ Server is running (port $PORT)"
  else
    echo "✗ Server is NOT running"
    exit 1
  fi
  exit 0
fi

if [ "$MODE" = "--stop" ]; then
  echo "Stopping latent KV server..."
  docker exec "$CONTAINER" bash -c \
    "pkill -f latent_kv_model_server 2>/dev/null && echo 'stopped' || echo 'not running'"
  exit 0
fi

# Check if already running
existing=$(check_running)
if [ "$existing" = "ok" ]; then
  echo "✓ Server already running on port $PORT"
  exit 0
fi

echo "Starting Latent KV Model Server"
echo "  Container : $CONTAINER"
echo "  GPU       : $GPU"
echo "  Model     : $MODEL_PATH"
echo "  Port      : $PORT"
echo "  Log       : $LOG_FILE"
echo ""

if [ "$MODE" = "--fg" ]; then
  # Foreground: logs to stdout
  docker exec "$CONTAINER" bash -c "
    cd $PROJECT
    export PYTHONPATH=\$PWD/src:\$PYTHONPATH
    export CUDA_VISIBLE_DEVICES=$GPU
    export LATENT_KV_SERVER_GPU=0    # after CUDA_VISIBLE_DEVICES remapping, it becomes device 0
    export LATENT_KV_SERVER_PORT=$PORT
    export VLLM_MODEL_PATH=$MODEL_PATH
    python3 src/latent_kv_model_server.py
  "
else
  # Background
  docker exec -d "$CONTAINER" bash -c "
    cd $PROJECT
    export PYTHONPATH=\$PWD/src:\$PYTHONPATH
    export CUDA_VISIBLE_DEVICES=$GPU
    export LATENT_KV_SERVER_GPU=0
    export LATENT_KV_SERVER_PORT=$PORT
    export VLLM_MODEL_PATH=$MODEL_PATH
    python3 src/latent_kv_model_server.py > $LOG_FILE 2>&1
  "
  wait_ready
  echo ""
  echo "Server ready. Verify:"
  echo "  docker exec $CONTAINER curl -s http://localhost:$PORT/health"
fi
