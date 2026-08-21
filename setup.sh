#!/data/data/com.termux/files/usr/bin/bash
# ClipForge AI — one-shot installer (Termux)
set -e
cd ~/clipper

echo "[1/6] Termux packages..."
pkg install -y python ffmpeg git make cmake clang pkg-config curl nodejs procps

echo "[2/6] Python deps..."
pip install --upgrade pip
pip install flask yt-dlp requests python-dotenv

echo "[3/6] whisper.cpp (any-language transcription)..."
if [ ! -d whisper.cpp ]; then git clone --depth 1 https://github.com/ggml-org/whisper.cpp; fi
cd whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j4
bash ./models/download-ggml-model.sh base
cd ..

echo "[4/6] llama.cpp (local AI server)..."
if [ ! -d llama.cpp ]; then git clone --depth 1 https://github.com/ggml-org/llama.cpp; fi
cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j2 --target llama-server llama-cli
cd ..

echo "[5/6] Local AI model (Qwen2.5-0.5B, free forever)..."
mkdir -p models
[ -f models/qwen2.5-0.5b-instruct-q4_k_m.gguf ] || \
  curl -L -o models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf

echo "[6/6] Config..."
[ -f .env ] || cat > .env << 'ENV'
AI_API_BASE=http://127.0.0.1:8080/v1
AI_MODEL=local
LLAMA_MODEL=models/qwen2.5-0.5b-instruct-q4_k_m.gguf
WHISPER_MODEL=whisper.cpp/models/ggml-base.bin
MAX_WORKERS=6
AI_TIMEOUT=240
ENV
[ -f cookies.txt ] || echo "# Export your YouTube cookies in the browser ON THIS DEVICE and save them here. This file must never be pushed anywhere." > cookies.txt

echo "✅ Done. Start with: bash run.sh"
