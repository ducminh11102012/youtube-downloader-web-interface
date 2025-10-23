from flask import Flask, request, send_file, render_template_string, redirect, url_for, jsonify
import yt_dlp, uuid, os, threading
from datetime import datetime, timedelta
import time

app = Flask(__name__)
DOWNLOAD_DIR = "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_FILE = os.path.join(os.getcwd(), "cookies.txt")  # nếu có cookies, để trống nếu không muốn dùng

FILES = {}  # file_id: {"url":..., "path":..., "expiry":..., "progress":0, "error":None}

TEMP_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Choose Format</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4">
<div class="container">
<h2>Choose format</h2>
<p>{{url}}</p>
<a href="/start/{{file_id}}?fmt=mp3" class="btn btn-primary">MP3</a>
<a href="/start/{{file_id}}?fmt=mp4" class="btn btn-success">MP4</a>
</div>
</body>
</html>
"""

PROGRESS_PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Downloading</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="p-4">
<div class="container">
<h2>Downloading...</h2>
<div class="progress" style="height:30px;">
  <div id="bar" class="progress-bar" role="progressbar" style="width:0%">0%</div>
</div>
<p id="status">Please wait...</p>
<div id="link" style="margin-top:15px;"></div>
</div>

<script>
let fid = "{{file_id}}";
function update(){
  fetch("/progress/"+fid).then(r=>r.json()).then(p=>{
    let bar = document.getElementById("bar");
    if(p.error){
      document.getElementById("status").innerText = "Error: "+p.error;
      return;
    }
    bar.style.width = p.percent+"%";
    bar.innerText = p.percent+"%";
    if(p.done){
      document.getElementById("status").innerText="Download complete!";
      document.getElementById("link").innerHTML='<a href="/file/'+fid+'" class="btn btn-primary">Download File</a>';
    } else {
      setTimeout(update, 1000);
    }
  });
}
update();
</script>
</body>
</html>
"""

@app.route("/", methods=["GET","POST"])
def index():
    if request.method=="POST":
        url = request.form.get("url")
        file_id = str(uuid.uuid4())
        FILES[file_id] = {"url":url,"path":None,"expiry":None,"progress":0,"error":None}
        return redirect(url_for("dl_temp", file_id=file_id))
    return """
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>YouTube Downloader</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="p-4">
    <div class="container">
    <h2>YouTube Downloader</h2>
    <form method="POST">
      <div class="mb-3">
        <label class="form-label">YouTube URL:</label>
        <input class="form-control" name="url" required>
      </div>
      <button class="btn btn-primary" type="submit">Next</button>
    </form>
    </div>
    </body>
    </html>
    """

@app.route("/dl-temp/<file_id>")
def dl_temp(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    return render_template_string(TEMP_PAGE, file_id=file_id, url=FILES[file_id]["url"])

def download_thread(url, fmt, file_id):
    ext = fmt
    out_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.{ext}")
    FILES[file_id]["progress"] = 0
    FILES[file_id]["error"] = None

    def progress_hook(d):
        if d.get("status")=="downloading":
            pct = d.get("_percent_str","0.0%").replace("%","")
            try: FILES[file_id]["progress"] = float(pct)
            except: pass
        elif d.get("status")=="finished":
            FILES[file_id]["progress"] = 100

    ydl_opts = {"outtmpl":out_path,"progress_hooks":[progress_hook]}
    if os.path.exists(COOKIES_FILE):
        ydl_opts["cookies"] = COOKIES_FILE

    if fmt=="mp3":
        ydl_opts["format"]="bestaudio"
        ydl_opts["postprocessors"]=[{"key":"FFmpegExtractAudio","preferredcodec":"mp3"}]
    else:
        ydl_opts["format"]="bestvideo+bestaudio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        FILES[file_id]["path"] = out_path
        FILES[file_id]["expiry"] = datetime.utcnow() + timedelta(hours=12)
    except Exception as e:
        FILES[file_id]["progress"] = -1
        FILES[file_id]["error"] = str(e)

@app.route("/start/<file_id>")
def start_download(file_id):
    if file_id not in FILES: return "Invalid or expired", 404
    fmt = request.args.get("fmt")
    if fmt not in ["mp3","mp4"]: return "Invalid format", 400
    url = FILES[file_id]["url"]
    threading.Thread(target=download_thread, args=(url, fmt, file_id)).start()
    return render_template_string(PROGRESS_PAGE, file_id=file_id)

@app.route("/progress/<file_id>")
def get_progress(file_id):
    if file_id not in FILES: return jsonify({"percent":0,"done":False})
    info = FILES[file_id]
    if info["progress"] < 0:
        return jsonify({"percent":0,"done":False,"error":info["error"]})
    done = info["progress"]>=100 and info["path"] is not None
    return jsonify({"percent":int(info["progress"]),"done":done})

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
