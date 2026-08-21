#!/data/data/com.termux/files/usr/bin/bash

termux-wake-lock
cd ~/clipper

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

LLAMA_SERVER="$HOME/clipper/llama.cpp/build/bin/llama-server"

if [[ "$LLAMA_MODEL" != /* ]]; then
  MODEL_PATH="$HOME/clipper/$LLAMA_MODEL"
else
  MODEL_PATH="$LLAMA_MODEL"
fi

if [ -x "$LLAMA_SERVER" ] && [ -f "$MODEL_PATH" ]; then
  pkill -f "llama-server" || true
  sleep 1

  "$LLAMA_SERVER" \
    -m "$MODEL_PATH" \
    --host 127.0.0.1 \
    --port 8080 \
    -c 16384 \
    -t 4 \
    --repeat-penalty 1.2 \
    > "$HOME/clipper/logs/llama.log" 2>&1 &

  sleep 10
fi

python app.py
