# 📖 ClipForge AI — Complete Install Guide
Turn any Android phone into a viral clip studio. 100% free, 100% on-device.

## What it does
1. Paste any YouTube link (any language)
2. Grabs the full transcript with timestamps (YouTube subs; whisper.cpp fallback)
3. On-device AI picks the most viral 20–120 second moments
4. Downloads ONLY those sections (never the whole video)
5. Forges vertical 9:16 MP4s (H.264 + AAC) that import into CapCut / Instagram / TikTok
6. Serves them in a premium web UI with one-tap save & delete

## What you need
- Android phone (~3 GB free storage)
- Termux installed from F-Droid (the Play Store version is outdated and broken)
- A YouTube account logged in on your phone browser (for cookies)
- ~15 minutes on first install

## Step 0 — Install Termux
1. Install F-Droid from f-droid.org
2. In F-Droid, search "Termux" and install it
3. Open Termux and run:
```bash
pkg update -y
```

## Step 1 — Clone the repo
```bash
pkg install git -y
git clone https://github.com/xm1n3tub3-ux/clipforge-ai-.git ~/clipper
cd ~/clipper
```
(Yes, the repo name really ends with a dash: `clipforge-ai-`)

## Step 2 — One-shot installer
```bash
bash setup.sh
```
It automatically:
- installs all Termux packages (python, ffmpeg, nodejs, cmake…)
- installs Python deps (flask, yt-dlp, requests…)
- builds whisper.cpp (transcription) + downloads its model
- builds llama.cpp (local AI server) + downloads the Qwen2.5-0.5B model
- writes `.env` config and a `cookies.txt` placeholder

First run takes 10–20 minutes depending on phone & network. Every run after is instant.

## Step 3 — Add your YouTube cookies (important)
YouTube blocks anonymous downloaders with "sign in to confirm you're not a bot". Your own cookies solve it.

**Firefox method:**
1. Install Firefox + a "cookies.txt" exporter add-on
2. Open youtube.com (make sure you are logged in)
3. Tap the add-on → export → save to Downloads
4. In Termux:
```bash
termux-setup-storage
cp ~/storage/shared/Download/cookies.txt ~/clipper/cookies.txt
```

**Kiwi Browser method:** same flow using the "Get cookies.txt LOCALLY" extension.

🔒 Your cookies stay on your device forever — the file is in `.gitignore` and is never uploaded anywhere.

## Step 4 — Launch
```bash
bash run.sh
```
Open in any browser:
- On the phone: `http://127.0.0.1:5000`
- Another device on the same Wi‑Fi: `http://<phone-ip>:5000` (the second address printed at startup)

## Step 5 — Forge clips
1. Paste a YouTube link
2. Pick a niche (or type your own)
3. Tap **Forge Viral Clips**
4. Watch the steps light up: Transcribe → AI Scoring → 4K Forge → Ready
5. Preview each clip, **Save** it, **Copy Caption**, or **Delete All Clips** to free storage

## Optional config (`nano ~/clipper/.env`)
| Key | Default | What it does |
|---|---|---|
| MAX_WORKERS | 6 | parallel clip downloads (lower if the phone gets hot) |
| AI_TIMEOUT | 240 | seconds before the AI gives up (instant scorer takes over) |
| OUT_RES | 1080p | output resolution (1080p = mobile-safe for CapCut/Insta) |
| WHISPER_MODEL | whisper.cpp/models/ggml-base.bin | transcription model |
| LLAMA_MODEL | models/qwen2.5-0.5b-instruct-q4_k_m.gguf | local AI model |

Restart after editing: `pkill -f "python app.py"; bash run.sh`

## Updating later
```bash
cd ~/clipper
git pull
bash run.sh
```

## Troubleshooting
| Symptom | Fix |
|---|---|
| `repository not found` | the URL must end with `clipforge-ai-.git` (trailing dash) |
| "Sign in to confirm you're not a bot" | cookies missing or expired → re-export (Step 3) |
| All clip downloads failed | check cookies + internet; details in `logs/clipper.log` |
| Stuck on AI Scoring | local AI is slow on some phones — it auto-falls-back to the instant scorer; see `logs/llama.log` |
| Address already in use | `pkill -f "python app.py"` then `bash run.sh` |
| Setup failed halfway | run `bash setup.sh` again — it resumes safely |

## Project layout
clipper/
├── app.py                # Flask web server + API
├── clipper.py            # pipeline: transcript → AI → download → forge
├── run.sh                # starts local AI server + web app
├── setup.sh              # one-shot installer
├── templates/index.html  # the studio UI
├── .env.example          # config template
└── cookies.txt           # YOURS — device-only, git-ignored
## Privacy & cost
- Zero cloud APIs, zero bills — transcription and AI run on your phone
- Cookies and clips never leave the device
- Everything else is open source
