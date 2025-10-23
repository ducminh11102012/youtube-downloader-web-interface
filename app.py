from flask import Flask, request, send_file, render_template_string, redirect, url_for
import yt_dlp, uuid, os, threading
from datetime import datetime, timedelta
import time

app = Flask(__name__)
DOWNLOAD_DIR = "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FILES = {}  # file_id: {"path":..., "expiry":...}

TEMP_PAGE = """
<!doctype html>
<title>Download Temp</title>
<h2>Choose format for download</h2>
<p>{{url}}</p>
<a href="/start/{{file_id}}?fmt=mp3"><button>MP3</button></a>
<a href="/start/{{file_id}}?fmt=mp4"><button>MP4</button></a>
"""

LINK_PAGE = """
<!doctype html>
<title>Download Ready</title>
<h2>Your download is ready</h2>
<p>Use wget/curl to download (valid 12h):</p>
<p><a href="{{link}}">{{link}}</a></p>
"""

@app.route("/", methods=["GET","POST"])
def index():
    if request.method=="POST":
        url = request.form.get("url")
        file_id = str(uuid.uuid4())
        # Save temp info
        FILES[file_id] = {"url":url, "path":None, "expiry":None}
        return redirect(url_for("dl_temp", file_id=file_id))
    return """
    <!doctype html>
    <title>YouTube Downloader</title>
    <h2>Enter YouTube URL</h2>
    <form method="POST">
      URL: <input name="url" required>
      <button type="submit">Next</button>
    </form>
    """

@app.route("/dl-temp/<file_id>")
def dl_temp(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    url = FILES[file_id]["url"]
    return render_template_string(TEMP_PAGE, file_id=file_id, url=url)

def download_thread(url, fmt, file_id):
    ext = fmt
    out_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.{ext}")
    ydl_opts = {"outtmpl":out_path}
    if fmt=="mp3":
        ydl_opts["format"]="bestaudio"
        ydl_opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"mp3"}]
    else:
        ydl_opts["format"]="bestvideo+bestaudio"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    FILES[file_id]["path"] = out_path
    FILES[file_id]["expiry"] = datetime.utcnow() + timedelta(hours=12)

@app.route("/start/<file_id>")
def start_download(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    fmt = request.args.get("fmt")
    if fmt not in ["mp3","mp4"]: return "Invalid format", 400
    url = FILES[file_id]["url"]
    threading.Thread(target=download_thread, args=(url, fmt, file_id)).start()
    return f"""
    <!doctype html>
    <title>Downloading...</title>
    <h2>Downloading in background...</h2>
    <p>Refresh <a href="/link/{file_id}">here</a> to get your link once done.</p>
    """

@app.route("/link/<file_id>")
def get_link(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    info = FILES[file_id]
    if not info["path"]: return "Still downloading...", 200
    direct_link = f"/file/{file_id}"
    return render_template_string(LINK_PAGE, link=direct_link)

@app.route("/file/<file_id>")
def download_file(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    info = FILES[file_id]
    if not info["path"]: return "Not ready", 400
    return send_file(info["path"], as_attachment=True)

def cleanup():
    while True:
        now = datetime.utcnow()
        for fid in list(FILES.keys()):
            info = FILES[fid]
            if info["expiry"] and info["expiry"] < now:
                try: os.remove(info["path"])
                except: pass
                del FILES[fid]
        time.sleep(600)

threading.Thread(target=cleanup, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5000)
