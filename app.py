import threading
import uuid
import traceback
import os
import glob
from flask import Flask, request, jsonify, render_template, send_from_directory
from clipper import process_video, CLIPS_DIR

app = Flask(__name__)

JOBS = {}
LOCK = threading.Lock()

def human_size(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024.0
    return f"{n:.1f} TB"

def cleanup_old_clips():
    if CLIPS_DIR.exists():
        for f in glob.glob(f"{CLIPS_DIR}/*"):
            try: os.remove(f)
            except Exception: pass

def update_job(job_id, **kwargs):
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)

def job_worker(job_id, url, niche):
    try:
        def progress(stage, percent, message):
            update_job(job_id, status="processing", stage=stage, percent=percent, message=message)

        update_job(job_id, status="processing", stage="starting", percent=1, message="Starting pipeline")
        result = process_video(url, niche, progress)

        clips = []
        for clip in result.get("clips", []):
            try: size = human_size(os.path.getsize(clip["path"]))
            except Exception: size = ""
            clips.append({
                "file": clip["file"], "caption": clip["caption"],
                "start": clip["start"], "end": clip["end"], "size": size,
                "url": f"/clips/{clip['file']}", "download": f"/clips/{clip['file']}?download=1"
            })

        update_job(job_id, status="complete", stage="done", percent=100, message="Complete",
                   result={"video_id": result.get("video_id"), "duration": result.get("duration"), "clips": clips})
    except Exception as exc:
        update_job(job_id, status="error", stage="error", percent=100, message=str(exc), error=traceback.format_exc())

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    niche = (data.get("niche") or "Auto").strip()
    if not url: return jsonify({"error": "URL is required"}), 400

    cleanup_old_clips()
    job_id = uuid.uuid4().hex[:12]

    with LOCK:
        JOBS[job_id] = {"id": job_id, "url": url, "niche": niche, "status": "queued",
                        "stage": "queued", "percent": 0, "message": "Queued", "result": {"clips": []}}

    threading.Thread(target=job_worker, args=(job_id, url, niche), daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/jobs/<job_id>")
def get_job(job_id):
    with LOCK: job = JOBS.get(job_id)
    if not job: return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route("/api/clips")
def list_clips():
    items = []
    if CLIPS_DIR.exists():
        for f in sorted(CLIPS_DIR.glob("*.mp4")):
            try: size = human_size(f.stat().st_size)
            except Exception: size = ""
            items.append({"file": f.name, "size": size,
                          "url": f"/clips/{f.name}", "download": f"/clips/{f.name}?download=1"})
    return jsonify({"clips": items})

@app.route("/api/clear", methods=["POST"])
def clear_clips():
    count = 0
    if CLIPS_DIR.exists():
        for f in glob.glob(f"{CLIPS_DIR}/*"):
            try:
                os.remove(f)
                count += 1
            except Exception: pass
    return jsonify({"deleted": count})

@app.route("/clips/<path:filename>")
def serve_clip(filename):
    if request.args.get("download") == "1":
        return send_from_directory(CLIPS_DIR, filename, as_attachment=True)
    return send_from_directory(CLIPS_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
