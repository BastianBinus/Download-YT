import socket
import threading
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
import yt_dlp

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")

app = Flask(__name__)

jobs = {}
jobs_lock = threading.Lock()


def run_download(job_id, url):
    def hook(d):
        with jobs_lock:
            job = jobs[job_id]
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    job["percent"] = round(downloaded / total * 100, 1)
                job["status"] = "downloading"
            elif d["status"] == "finished":
                job["status"] = "processing"

    ydl_opts = {
        "format": "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(DOWNLOAD_DIR / "%(title).150B [%(id)s].%(ext)s"),
        "progress_hooks": [hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_id = info.get("id", "")
        candidates = [
            p for p in DOWNLOAD_DIR.iterdir()
            if p.is_file() and video_id and video_id in p.name
        ]
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            filename = candidates[0].name
        else:
            filename = Path(ydl.prepare_filename(info)).name

        with jobs_lock:
            jobs[job_id].update(
                status="finished",
                percent=100,
                filename=filename,
                title=info.get("title"),
            )
    except Exception as exc:  # noqa: BLE001 - surface any download failure to the UI
        with jobs_lock:
            jobs[job_id].update(status="error", error=str(exc))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing URL"}), 400
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "That doesn't look like a URL"}), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "percent": 0,
            "filename": None,
            "error": None,
            "title": None,
        }
    threading.Thread(target=run_download, args=(job_id, url), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    return jsonify(job)


@app.route("/api/videos")
def api_videos():
    videos = []
    for f in sorted(DOWNLOAD_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
            videos.append({"name": f.name, "size": f.stat().st_size})
    return jsonify(videos)


def _safe_path(filename):
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        abort(400)
    path = (DOWNLOAD_DIR / filename).resolve()
    if DOWNLOAD_DIR.resolve() not in path.parents:
        abort(400)
    return path


@app.route("/videos/<path:filename>")
def serve_video(filename):
    _safe_path(filename)
    return send_from_directory(DOWNLOAD_DIR, filename, conditional=True)


@app.route("/api/videos/<path:filename>", methods=["DELETE"])
def delete_video(filename):
    path = _safe_path(filename)
    if not path.exists():
        abort(404)
    path.unlink()
    return jsonify({"ok": True})


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ip = local_ip()
    print("=" * 50)
    print("  Swamp Grabber is hopping!")
    print(f"  On this PC:   http://127.0.0.1:5000")
    print(f"  On your phone (same WiFi): http://{ip}:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
