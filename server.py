from http.server import SimpleHTTPRequestHandler, HTTPServer
import os, json, subprocess, tempfile, shutil
import socket, ipaddress
import urllib.request, urllib.error
from urllib.parse import urlsplit

from urllib.parse import urlparse, parse_qs
from engine.groq import ask_groq

PORT = 8080


def fetch_media_url(url, limit=200 * 1024 * 1024):
    parsed = urlsplit(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Please use a valid HTTPS direct media URL")

    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Unsupported URL")

    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Cannot resolve media host")

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("Private or local addresses are not allowed")

    request = urllib.request.Request(
        url, headers={"User-Agent": "LOTAYA-AI-PLAYER/1.0"}
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("Media server did not return HTTP 200")

        content_type = response.headers.get("Content-Type", "")
        data = response.read(limit + 1)

    if len(data) > limit:
        raise ValueError("Media file exceeds 200 MB")

    return data, content_type


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.path = "/www/index.html"
        return super().do_GET()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)

            if parsed.path == "/api/convert-mp3":
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 200 * 1024 * 1024:
                    return self.send_json({"error": "File must be under 200 MB"}, 413)

                folder = tempfile.mkdtemp(prefix="lotaya_mp3_", dir=os.getcwd())
                try:
                    source = os.path.join(folder, "input_video")
                    output = os.path.join(folder, "converted.mp3")

                    with open(source, "wb") as f:
                        f.write(self.rfile.read(length))

                    result = subprocess.run(
                        ["ffmpeg", "-y", "-i", source, "-vn",
                         "-codec:a", "libmp3lame", "-q:a", "2", output],
                        capture_output=True, text=True, timeout=1800
                    )

                    if result.returncode != 0 or not os.path.exists(output):
                        return self.send_json({"error": "MP3 conversion failed"}, 500)

                    with open(output, "rb") as f:
                        mp3_data = f.read()

                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Disposition", 'attachment; filename="LOTAYA_Audio.mp3"')
                    self.send_header("Content-Length", str(len(mp3_data)))
                    self.end_headers()
                    self.wfile.write(mp3_data)
                    return
                finally:
                    shutil.rmtree(folder, ignore_errors=True)

            if parsed.path == "/api/download-mp4":
                data_length = int(self.headers.get("Content-Length", 0))
                if data_length <= 0 or data_length > 200 * 1024 * 1024:
                    return self.send_json({"error": "Video must be under 200 MB"}, 413)

                folder = os.path.join(os.getcwd(), "downloads")
                os.makedirs(folder, exist_ok=True)
                filename = "LOTAYA_Video.mp4"
                target = os.path.join(folder, filename)

                with open(target, "wb") as f:
                    f.write(self.rfile.read(data_length))

                return self.send_json({
                    "success": True,
                    "filename": filename,
                    "message": "MP4 saved in downloads folder"
                })


            if parsed.path in ("/api/download-mp4-url", "/api/download-mp3-url"):
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 10000:
                    return self.send_json({"error": "Invalid URL request"}, 400)

                data = json.loads(self.rfile.read(length))
                url = data.get("url", "").strip()
                if not url:
                    return self.send_json({"error": "Please enter a media URL"}, 400)

                media, content_type = fetch_media_url(url)

                if parsed.path == "/api/download-mp4-url":
                    if not (content_type.startswith("video/") or
                            content_type == "application/octet-stream"):
                        return self.send_json({"error": "URL does not appear to be a video file"}, 400)

                    folder = os.path.join(os.getcwd(), "downloads")
                    os.makedirs(folder, exist_ok=True)
                    target = os.path.join(folder, "LOTAYA_Link_Video.mp4")
                    with open(target, "wb") as f:
                        f.write(media)

                    return self.send_json({
                        "success": True,
                        "message": "MP4 saved in downloads folder"
                    })

                folder = tempfile.mkdtemp(prefix="lotaya_url_mp3_", dir=os.getcwd())
                try:
                    source = os.path.join(folder, "source")
                    output = os.path.join(folder, "LOTAYA_Link_Audio.mp3")

                    with open(source, "wb") as f:
                        f.write(media)

                    result = subprocess.run(
                        ["ffmpeg", "-y", "-i", source, "-vn",
                         "-codec:a", "libmp3lame", "-q:a", "2", output],
                        capture_output=True, text=True, timeout=1800
                    )

                    if result.returncode != 0 or not os.path.exists(output):
                        return self.send_json({"error": "Could not convert this link to MP3"}, 500)

                    with open(output, "rb") as f:
                        mp3_data = f.read()

                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Content-Disposition", 'attachment; filename="LOTAYA_Link_Audio.mp3"')
                    self.send_header("Content-Length", str(len(mp3_data)))
                    self.end_headers()
                    self.wfile.write(mp3_data)
                    return
                finally:
                    shutil.rmtree(folder, ignore_errors=True)

            if parsed.path == "/api/auto-subtitle":
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 500 * 1024 * 1024:
                    return self.send_json({"error": "Video must be under 500 MB"}, 413)

                params = parse_qs(parsed.query)
                language = params.get("language", ["auto"])[0]
                if language not in ("auto", "my", "en"):
                    language = "auto"

                filename = params.get("filename", ["video.mp4"])[0]
                ext = os.path.splitext(os.path.basename(filename))[1].lower()
                if ext not in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"):
                    ext = ".mp4"

                folder = tempfile.mkdtemp(prefix="lotaya_", dir=os.getcwd())
                try:
                    video = os.path.join(folder, "input" + ext)
                    audio = os.path.join(folder, "audio.wav")
                    output = os.path.join(folder, "subtitle")

                    with open(video, "wb") as f:
                        f.write(self.rfile.read(length))

                    ff = subprocess.run(
                        ["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1",
                         "-ar", "16000", "-c:a", "pcm_s16le", audio],
                        capture_output=True, text=True
                    )
                    if ff.returncode != 0:
                        return self.send_json({"error": "Could not extract audio from video"}, 500)

                    root = os.path.dirname(os.path.abspath(__file__))
                    whisper = os.path.join(root, "engine/whisper.cpp/build/bin/whisper-cli")
                    model = os.path.join(root, "engine/whisper.cpp/models/ggml-base.bin")

                    result = subprocess.run(
                        [whisper, "-m", model, "-f", audio, "-l", "auto", "-tr",
                         "-osrt", "-of", output, "-t", "4"],
                        capture_output=True, text=True, timeout=3600
                    )
                    srtfile = output + ".srt"
                    if result.returncode != 0 or not os.path.exists(srtfile):
                        return self.send_json({"error": "Whisper subtitle generation failed"}, 500)

                    with open(srtfile, "r", encoding="utf-8") as f:
                        return self.send_json({"srt": f.read()})
                finally:
                    shutil.rmtree(folder, ignore_errors=True)

            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 200000:
                return self.send_json({"error": "Invalid request"}, 400)

            data = json.loads(self.rfile.read(length))

            if self.path == "/api/chat":
                answer = ask_groq(data.get("message", ""))
                return self.send_json({"reply": answer})

            if self.path == "/api/translate":
                texts = data.get("texts", [])
                language = data.get("language", "Burmese")

                if not isinstance(texts, list) or len(texts) > 20:
                    return self.send_json({"error": "Maximum 20 subtitles per request"}, 400)

                prompt = (
                    "Translate these subtitle lines into " + language +
                    ". Preserve their order. Return ONLY a valid JSON array "
                    "of translated strings. Do not add explanations.\n"
                    + json.dumps(texts, ensure_ascii=False)
                )

                answer = ask_groq(prompt)

                if answer.startswith("HTTP ") or answer.startswith("AI Error"):
                    return self.send_json({"error": answer}, 502)

                start = answer.find("[")
                end = answer.rfind("]")

                if start < 0 or end < start:
                    return self.send_json({"error": "Invalid AI translation response"}, 502)

                translated = json.loads(answer[start:end+1])

                if not isinstance(translated, list) or len(translated) != len(texts):
                    return self.send_json({"error": "Translation count mismatch"}, 502)

                return self.send_json({"translations": translated})

            return self.send_json({"error": "Not found"}, 404)

        except Exception as e:
            return self.send_json({"error": str(e)}, 500)

os.chdir(os.path.dirname(os.path.abspath(__file__)))
server = HTTPServer(("0.0.0.0", PORT), Handler)

print("LOTAYA AI PLAYER SERVER STARTED")
print("AI CHAT + SUBTITLE TRANSLATION READY")
print("Open: http://127.0.0.1:8080")
server.serve_forever()
