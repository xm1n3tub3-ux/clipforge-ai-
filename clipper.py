import os
import re
import json
import time
import random
import shutil
import logging
import subprocess
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TRANSCRIPT_DIR = BASE_DIR / "transcripts"
AUDIO_DIR = BASE_DIR / "audio"
CLIPS_DIR = BASE_DIR / "clips"
LOG_DIR = BASE_DIR / "logs"

for folder in (TRANSCRIPT_DIR, AUDIO_DIR, CLIPS_DIR, LOG_DIR):
    folder.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "clipper.log"), level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

AI_API_BASE = os.getenv("AI_API_BASE", "http://127.0.0.1:8080/v1").strip()
AI_MODEL = os.getenv("AI_MODEL", "local").strip()
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "240"))
WHISPER_DIR = BASE_DIR / "whisper.cpp"

PAD_START = 1.0
PAD_END = 1.0
MIN_CLIP = 20.0
MAX_CLIP = 120.0

model_env = os.getenv("WHISPER_MODEL", "whisper.cpp/models/ggml-base.en.bin")
MODEL_PATH = Path(model_env)
if not MODEL_PATH.is_absolute(): MODEL_PATH = BASE_DIR / MODEL_PATH

SKIP_PREFIXES = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

VIRAL_WORDS = ["secret", "truth", "money", "ai", "hack", "how", "why", "never", "stop",
    "success", "mindset", "viral", "shocking", "life", "future", "rich", "power", "tech",
    "crypto", "business", "story", "dark", "fact", "believe", "change", "habit", "focus",
    "win", "lose", "fear", "pain", "million", "crazy", "insane", "impossible", "genius",
    "raaz", "kamaal", "paisa", "kamyabi", "sach", "gupt", "soch", "zindagi", "tarika",
    "secreto", "dinero", "verdad", "increible", "millonario", "exitoso",
    "geheimnis", "wahrheit", "geld", "erfolg",
    "segredo", "dinheiro", "sucesso", "segreto", "soldi", "verita"]

def find_cookies():
    candidates = [BASE_DIR / "cookies.txt", Path.home() / "storage" / "shared" / "Download" / "cookies.txt"]
    for c in candidates:
        if c.exists(): return c
    return None

COOKIES_PATH = find_cookies()
logging.info("Boot | cookies:%s workers:%s", COOKIES_PATH, MAX_WORKERS)

def run_command(command):
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = proc.stderr[-600:]
        raise RuntimeError("rc=" + str(proc.returncode) + " | " + " ".join(map(str, command)) + " | " + tail)
    return proc.stdout

def run_yt(cmd, tries=3):
    last = None
    for attempt in range(tries):
        try: return run_command(cmd)
        except Exception as e:
            last = e
            logging.info("yt-dlp attempt %s failed: %s", attempt + 1, str(e)[:200])
            time.sleep(2 + attempt * 2)
    raise last

def yt_base():
    args = ["yt-dlp"]
    if shutil.which("node"): args += ["--js-runtimes", "node"]
    args += ["--remote-components", "ejs:github"]
    args += ["-N", "16"]
    if COOKIES_PATH:
        args += ["--cookies", str(COOKIES_PATH)]
    else:
        args += ["--user-agent", random.choice(USER_AGENTS)]
    args += ["--retries", "3", "--fragment-retries", "3"]
    return args

def sanitize_filename(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value[:120] or "clip"

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def find_whisper_binary():
    for c in [WHISPER_DIR / "build" / "bin" / "whisper-cli", WHISPER_DIR / "build" / "bin" / "main"]:
        if c.exists(): return str(c)
    raise FileNotFoundError("whisper.cpp binary not found.")

def parse_timestamp(value):
    if value is None: return 0.0
    value = str(value).strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
        return float(value)
    except ValueError: return 0.0

def parse_vtt_to_segments(sub_path):
    text = sub_path.read_text(encoding='utf-8', errors='ignore')
    lines = text.split('\n')
    segments = []
    time_pattern = re.compile(r'(\d{1,2}:?\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{1,2}:?\d{2}:\d{2}[.,]\d{3})')
    current_text, start_time, end_time = [], 0.0, 0.0

    def flush():
        nonlocal current_text, start_time, end_time
        if current_text and start_time > 0:
            segments.append({"start": start_time, "end": end_time, "text": " ".join(current_text).strip()})
        current_text, start_time, end_time = [], 0.0, 0.0

    for line in lines:
        line = line.strip()
        if not line: flush(); continue
        match = time_pattern.match(line)
        if match:
            flush()
            start_time = parse_timestamp(match.group(1))
            end_time = parse_timestamp(match.group(2))
        else:
            clean_line = re.sub(r'<[^>]+>', '', line).strip()
            if clean_line and not clean_line.startswith(SKIP_PREFIXES) and not re.match(r'^\d+$', clean_line):
                current_text.append(clean_line)
    flush()
    return segments

def get_transcript_fast(url):
    cmd = yt_base() + ["--skip-download",
                       "--print", "%(id)s",
                       "--print", "%(duration)s",
                       "--print", "%(language)s",
                       url]
    out = run_yt(cmd, tries=2).strip().splitlines()
    if len(out) < 3:
        raise RuntimeError("Could not read video metadata")
    video_id = out[0].strip()
    try: duration = float(out[1].strip() or 0)
    except Exception: duration = 0.0
    lang = (out[2].strip().lower() if len(out) > 2 else "") or ""
    base_lang = lang.split("-")[0].split(".")[0] if lang else "en"
    logging.info("Video id: %s | lang: %s | duration: %s", video_id, lang or "unknown", duration)

    attempts = []
    if base_lang: attempts.append(base_lang + ".*," + base_lang)
    if lang and lang != base_lang: attempts.append(lang + ".*," + lang)
    attempts += ["en.*,en", ".*"]

    for pattern in attempts:
        sub_cmd = yt_base() + ["--write-subs", "--write-auto-subs",
                               "--sub-lang", pattern, "--skip-download",
                               "-o", str(TRANSCRIPT_DIR / video_id), url]
        try: run_yt(sub_cmd, tries=1)
        except Exception as e:
            logging.info("Sub attempt %s: %s", pattern, str(e)[:100])

        files = sorted(TRANSCRIPT_DIR.glob(f"{video_id}*.vtt")) + sorted(TRANSCRIPT_DIR.glob(f"{video_id}*.srt"))
        if base_lang:
            files = sorted([f for f in files if base_lang in f.stem]) + files
        for p in files:
            segs = parse_vtt_to_segments(p)
            if segs:
                logging.info("Parsed %s segments from %s (lang=%s)", len(segs), p.name, base_lang)
                return segs, video_id, duration

    logging.info("No subs found, whisper fallback")
    audio_cmd = yt_base() + ["-f", "bestaudio[abr<=64]/worstaudio", "-o", str(AUDIO_DIR / f"{video_id}.%(ext)s"), url]
    run_yt(audio_cmd)
    audio_files = [f for f in AUDIO_DIR.glob(f"{video_id}.*") if f.suffix != ".wav"]
    if not audio_files: raise RuntimeError("No subtitles and no audio.")
    audio_path = audio_files[0]
    wav_path = AUDIO_DIR / f"{video_id}.wav"
    run_command(["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)])
    whisper_bin = find_whisper_binary()
    out_prefix = TRANSCRIPT_DIR / video_id
    try:
        run_command([whisper_bin, "-m", str(MODEL_PATH), "-f", str(wav_path), "-fa", "-l", "auto", "-otxt", "-oj", "-of", str(out_prefix)])
    except Exception:
        run_command([whisper_bin, "-m", str(MODEL_PATH), "-f", str(wav_path), "-l", "auto", "-otxt", "-oj", "-of", str(out_prefix)])
    json_path = Path(str(out_prefix) + ".json")
    segments = parse_whisper_json(json_path) if json_path.exists() else []
    try: audio_path.unlink()
    except Exception: pass
    try: wav_path.unlink()
    except Exception: pass
    return segments, video_id, duration

def parse_whisper_json(json_path):
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    items = data.get("transcription") or data.get("segments") or data.get("result") or [] if isinstance(data, dict) else data
    segments = []
    for item in items:
        if not isinstance(item, dict): continue
        text = (item.get("text") or "").strip()
        if not text: continue
        start, end = 0.0, 0.0
        if isinstance(item.get("offsets"), dict):
            start = float(item["offsets"].get("from", 0)) / 1000.0
            end = float(item["offsets"].get("to", 0)) / 1000.0
        elif isinstance(item.get("timestamps"), dict):
            start, end = parse_timestamp(item["timestamps"].get("from")), parse_timestamp(item["timestamps"].get("to"))
        elif "start" in item and "end" in item:
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
        segments.append({"start": start, "end": end, "text": text})
    return segments

def heuristic_candidates(segments, duration, niche):
    niche_words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", niche or "")]
    def score_text(text):
        low = text.lower()
        s = sum(2 for w in VIRAL_WORDS + niche_words if w in low)
        s += min(text.count("!"), 3) * 2
        s += min(text.count("?"), 3) * 3
        s += min(sum(c.isdigit() for c in text), 6)
        if len(text) > 120: s += 2
        return s
    candidates = []
    i, n = 0, len(segments)
    while i < n:
        start = segments[i]["start"]
        parts, end, j, best = [], start, i, None
        while j < min(n, i + 80):
            parts.append(segments[j]["text"])
            end = segments[j]["end"]
            length = end - start
            if length > MAX_CLIP: break
            if length >= MIN_CLIP:
                text = " ".join(parts)
                sc = score_text(text) + (5 if 40 <= length <= 90 else 0)
                if best is None or sc > best["score"]:
                    best = {"start": start, "end": end, "caption": text[:140], "score": sc}
            j += 1
        if best: candidates.append(best)
        i = max(i + 1, j)
    return candidates


def validate_and_rank_clips(candidates, duration, target):
    valid = []
    for c in candidates:
        try:
            s = max(0.0, float(c["start"])); e = min(duration, float(c["end"]))
        except Exception: continue
        if e - s < MIN_CLIP: e = min(duration, s + 45)
        if e - s > MAX_CLIP: e = s + MAX_CLIP
        if e - s >= MIN_CLIP - 2:
            valid.append({"start": round(s, 3), "end": round(e, 3), "caption": c.get("caption", "Viral moment"), "score": float(c.get("score", 0))})
    valid.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    for c in valid:
        if not any(c["start"] < e["end"] and c["end"] > e["start"] for e in selected):
            selected.append(c)
        if len(selected) >= target: break
    return selected[:target]

def even_spaced_clips(duration, target):
    if duration <= 0: return []
    clips, step = [], max(60, duration / (target + 1))
    t = step / 2
    while len(clips) < target and t + 60 <= duration:
        clips.append({"start": round(t, 3), "end": round(min(t + 60, duration), 3), "caption": f"Clip {len(clips)+1}", "score": 1.0})
        t += step
    return clips

def call_local_ai(system, user):
    url = AI_API_BASE.rstrip("/") + "/chat/completions"
    payload = {"model": AI_MODEL, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "temperature": 0.7, "max_tokens": 300, "stream": False}
    r = requests.post(url, json=payload, timeout=AI_TIMEOUT)
    if r.status_code >= 400: raise RuntimeError(f"Local AI {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]

def ai_rerank(candidates, niche, target):
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    top = ranked[:min(20, len(ranked))]
    lines = [f"{i+1}. [{c['start']:.0f}-{c['end']:.0f}] {c['caption'][:100]}" for i, c in enumerate(top)]
    system = "You pick the most viral short-video moments from a list. Reply ONLY with comma-separated numbers."
    user = f"Niche: {niche}. Pick the best {min(target, len(top))} numbers:\n" + "\n".join(lines)
    content = call_local_ai(system, user)
    logging.info("AI rerank output: %s", content)
    picked = []
    for n in re.findall(r"\d+", content):
        idx = int(n) - 1
        if 0 <= idx < len(top) and top[idx] not in picked:
            picked.append(top[idx])
        if len(picked) >= target: break
    if not picked: raise RuntimeError("No numbers parsed")
    return picked

def agentreach_select_clips(segments, duration, niche, progress=None):
    target = max(1, min(15, max(3, int(duration // 60))))
    candidates = heuristic_candidates(segments, duration, niche)
    if not candidates: return even_spaced_clips(duration, target)
    try:
        ai_ranked = ai_rerank(candidates, niche, target)
        if ai_ranked:
            logging.info("AI re-ranked %s diverse clips", len(ai_ranked))
            return ai_ranked
    except Exception as e:
        logging.error("AI rerank failed, using pure heuristic: %s", e)
    return validate_and_rank_clips(candidates, duration, target)


def transcode_mobile_4k(src, final):
    vf = "scale=-2:1080:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    base = ["ffmpeg", "-y", "-i", str(src)]
    attempts = [
        base + ["-vf", vf, "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2",
                "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", "-movflags", "+faststart", str(final)],
        base + ["-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                "-movflags", "+faststart", str(final)],
        base + ["-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k",
                "-movflags", "+faststart", str(final)],
    ]
    last = None
    for cmd in attempts:
        try:
            run_command(cmd)
            return
        except Exception as e:
            last = e
    raise last

def download_one(url, s, e, tmp_stem, final):
    fmt = "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/bv*[vcodec^=avc1][height<=1080]+ba/b[height<=1080]"
    cmd = yt_base() + ["--download-sections", f"*{format_time(s)}-{format_time(e)}",
                       "-f", fmt, "--merge-output-format", "mp4",
                       "-o", str(tmp_stem) + ".%(ext)s", url]
    run_yt(cmd, tries=2)
    src = None
    for f in sorted(CLIPS_DIR.glob(tmp_stem.name + ".*")):
        if f.suffix.lower() in (".mp4", ".mkv", ".webm"):
            src = f
            break
    if not src: raise RuntimeError("section produced no file")
    try:
        transcode_mobile_4k(src, final)
    finally:
        try: src.unlink()
        except Exception: pass
    return final

def cut_clips(url, clips, duration, progress=None):
    padded = []
    for c in clips:
        s = max(0.0, c["start"] - PAD_START)
        e = min(duration, c["end"] + PAD_END)
        padded.append((s, e, c))

    results, futures = [], {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, (s, e, c) in enumerate(padded, 1):
            tmp_stem = CLIPS_DIR / f"clip_{i:03d}"
            final = CLIPS_DIR / (sanitize_filename(f"{i:02d}_{int(s)}-{int(e)}_{c['caption']}") + ".mp4")
            futures[ex.submit(download_one, url, s, e, tmp_stem, final)] = (i, s, e, c, final)
        done = 0
        for fut in as_completed(futures):
            i, s, e, c, final = futures[fut]
            done += 1
            try:
                path = fut.result()
                results.append({"file": Path(path).name, "path": str(path), "caption": c["caption"], "start": s, "end": e})
            except Exception as e2:
                logging.error("Clip %s failed: %s", i, str(e2)[:300])
            if progress: progress("cut", 70 + int(25 * done / max(len(padded), 1)), f"Clip {done}/{len(padded)} done")
    return sorted(results, key=lambda x: x["file"])

def process_video(url, niche="Auto", progress=None):
    def emit(stage, percent, message):
        if progress: progress(stage, percent, message)

    emit("transcript", 10, "Transcribing full video with timestamps")
    segments, video_id, duration = get_transcript_fast(url)
    logging.info("Got %s segments", len(segments))
    if not duration and segments: duration = segments[-1]["end"]
    if not duration: raise RuntimeError("Could not get duration.")

    emit("ai", 40, "AI picking viral moments (20s-2min)")
    clips = agentreach_select_clips(segments, duration, niche, progress)
    if not clips: raise RuntimeError("No clips selected.")

    emit("cut", 70, f"Forging {len(clips)} clips (vertical 1080p, mobile-safe)")
    cut_results = cut_clips(url, clips, duration, progress)
    if not cut_results: raise RuntimeError("All clip downloads failed.")

    emit("done", 100, "Finished!")

    try:
        for f in TRANSCRIPT_DIR.glob(f"{video_id}*"): f.unlink()
        for f in AUDIO_DIR.glob(f"{video_id}*"): f.unlink()
    except Exception as e: logging.warning("Cleanup: %s", e)

    return {"video_id": video_id, "duration": duration, "clips": cut_results}
