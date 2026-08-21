# ClipForge AI ⚡
Cinematic viral clip studio that runs 100% on a phone (Termux). Zero cloud cost.

Paste a YouTube link → full original-language transcript with timestamps → on-device AI picks the most viral 20–120s moments → downloads ONLY those sections → forges vertical 9:16 H.264 clips ready for CapCut, Instagram and TikTok.

## Pipeline
1. **Transcribe** — YouTube subtitles in the video's own language, whisper.cpp fallback for any spoken language
2. **AI Scoring** — local llama.cpp ranks the strongest hooks (no API bills)
3. **4K Forge** — section-only downloads, vertical 1080p H.264 + AAC encode, faststart MP4

## Run
pkg install python ffmpeg nodejs
pip install flask yt-dlp requests python-dotenv
cd ~/clipper && bash run.sh
Open http://127.0.0.1:5000
