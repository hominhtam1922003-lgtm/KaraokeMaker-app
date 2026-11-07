"""Karaoke Maker — app PC: tách beat AI, căn nhịp lời, xuất video karaoke.

Chạy một máy chủ web local (chỉ 127.0.0.1) và mở giao diện trong trình duyệt.
Đóng gói thành .exe bằng PyInstaller (xem KaraokeMaker.spec).
"""
import json
import os
import sys
import threading
import traceback
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    WEB_DIR = os.path.join(sys._MEIPASS, "web")
    ROOT = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "KaraokeMaker")
else:
    WEB_DIR = os.path.join(BASE, "web")
    ROOT = os.path.join(BASE, "work")
WORK = os.path.join(ROOT, "session")
os.makedirs(WORK, exist_ok=True)

sys.path.insert(0, BASE if not getattr(sys, "frozen", False) else sys._MEIPASS)
from karaoke import lyrics as lyr  # noqa: E402
from karaoke import media, mdx  # noqa: E402

STATE = {
    "song_name": None,
    "song_wav": None,       # WAV làm việc trích từ file gốc
    "duration": 0.0,
    "inst_wav": None,       # WAV beat đã tách
    "inst_mode": None,
    "bg_image": None,
    "bg_video": None,
    "out_mp4": None,
}
JOBS = {}
LOCK = threading.Lock()


def new_job(fn):
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"status": "running", "progress": 0.0, "label": "", "error": None,
                 "result": None}

    def runner():
        def cb(pct, label=""):
            with LOCK:
                JOBS[jid]["progress"] = round(float(pct), 1)
                if label:
                    JOBS[jid]["label"] = label
        try:
            res = fn(cb)
            with LOCK:
                JOBS[jid].update(status="done", progress=100.0, result=res)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                JOBS[jid].update(status="error", error=str(e))

    threading.Thread(target=runner, daemon=True).start()
    return jid


ACTIVE = {"separate": None, "render": None, "align": None, "autoall": None}


def any_job_running():
    """Có bất kỳ tác vụ nền nào đang chạy không — các tác vụ ghi chung bộ file
    trong thư mục session nên phải chạy lần lượt, không song song."""
    with LOCK:
        return any((JOBS.get(ACTIVE.get(k) or "") or {}).get("status") == "running"
                   for k in ACTIVE)


def start_job(kind, fn):
    """Chạy job theo loại; nếu loại đó đang có job chạy dở thì trả None
    (chặn bấm trùng hai tác vụ ghi cùng một file đầu ra)."""
    with LOCK:
        cur = JOBS.get(ACTIVE.get(kind) or "")
        if cur and cur["status"] == "running":
            return None
    jid = new_job(fn)
    ACTIVE[kind] = jid
    return jid


def serve_file(handler, path, content_type, download_name=None):
    size = os.path.getsize(path)
    rng = handler.headers.get("Range")
    start, end = 0, size - 1
    status = 200
    if rng and rng.startswith("bytes="):
        try:
            s, _, e = rng[6:].partition("-")
            if s:
                start = int(s)
                end = int(e) if e else size - 1
            elif e:  # "bytes=-N" = N byte cuối
                start = max(0, size - int(e))
                end = size - 1
            else:
                start, end = 0, size - 1
            end = min(end, size - 1)
            if start > end:
                raise ValueError("range ngoài file")
            status = 206
        except ValueError:
            start, end, status = 0, size - 1, 200
    length = end - start + 1
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    if download_name:
        handler.send_header("Content-Disposition",
                            f"attachment; filename*=UTF-8''"
                            f"{urllib.parse.quote(download_name)}")
    handler.end_headers()
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(1 << 18, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # tắt log ồn
        pass

    # ---------- helpers ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _body_json(self):
        raw = self._body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _resolve_bg(self, bg_req):
        """Chọn nền video từ yêu cầu: ảnh/video người dùng tải lên, mẫu
        gradient có sẵn (tạo ảnh 1 lần rồi dùng lại), hoặc màu trơn."""
        bg_req = bg_req or {}
        t = bg_req.get("type")
        if t == "image" and STATE["bg_image"]:
            return {"type": "image", "value": STATE["bg_image"]}
        if t == "video" and STATE["bg_video"]:
            return {"type": "video", "value": STATE["bg_video"]}
        if t == "gradient":
            kind = str(bg_req.get("value") or "demtim")
            path = os.path.join(WORK, f"grad_{kind}.png")
            if not os.path.exists(path):
                media.make_gradient_bg(kind, path)
            return {"type": "image", "value": path}
        return {"type": "color", "value": bg_req.get("value", "#0b0e1a")}

    # ---------- GET ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path.startswith("/static/"):
                name = os.path.basename(path)
                fpath = os.path.join(WEB_DIR, name)
                if not os.path.exists(fpath):
                    return self._json({"error": "not found"}, 404)
                ctype = ("text/css" if name.endswith(".css") else
                         "application/javascript" if name.endswith(".js") else
                         "application/octet-stream")
                serve_file(self, fpath, ctype)
            elif path.startswith("/api/job/"):
                jid = path.rsplit("/", 1)[-1]
                job = JOBS.get(jid)
                if not job:
                    return self._json({"error": "job không tồn tại"}, 404)
                self._json(job)
            elif path == "/api/state":
                self._json({k: (os.path.basename(v) if isinstance(v, str) and v else v)
                            for k, v in STATE.items()})
            elif path == "/api/audio/song" and STATE["song_wav"]:
                serve_file(self, STATE["song_wav"], "audio/wav")
            elif path == "/api/audio/inst" and STATE["inst_wav"]:
                serve_file(self, STATE["inst_wav"], "audio/wav")
            elif path == "/api/video" and STATE["out_mp4"]:
                serve_file(self, STATE["out_mp4"], "video/mp4")
            elif path == "/api/download" and STATE["out_mp4"]:
                serve_file(self, STATE["out_mp4"], "video/mp4",
                           download_name="karaoke.mp4")
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    # ---------- POST ----------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/upload-song":
                payload = self._body()
                if not payload:
                    return self._json({"error": "File rỗng — chưa chọn file nhạc?"}, 400)
                name = urllib.parse.unquote(
                    self.headers.get("X-File-Name") or "song.bin")
                ext = os.path.splitext(name)[1] or ".bin"
                src = os.path.join(WORK, "song_src" + ext)
                with open(src, "wb") as f:
                    f.write(payload)
                wav = os.path.join(WORK, "song.wav")
                media.extract_audio(src, wav)
                STATE.update(song_name=name, song_wav=wav,
                             duration=media.probe_duration(wav),
                             inst_wav=None, inst_mode=None, out_mp4=None)
                self._json({"ok": True, "name": name, "duration": STATE["duration"]})

            elif path in ("/api/upload-bg-image", "/api/upload-bg-video"):
                payload = self._body()
                if not payload:
                    return self._json({"error": "File rỗng — chưa chọn file?"}, 400)
                name = urllib.parse.unquote(
                    self.headers.get("X-File-Name") or "bg.bin")
                ext = os.path.splitext(name)[1] or ".bin"
                key = "bg_image" if path.endswith("image") else "bg_video"
                dst = os.path.join(WORK, key + ext)
                with open(dst, "wb") as f:
                    f.write(payload)
                if not media.check_readable(dst):
                    os.remove(dst)
                    return self._json(
                        {"error": "File không đọc được — không đúng định dạng "
                                  "ảnh/video"}, 400)
                STATE[key] = dst
                self._json({"ok": True, "name": name})

            elif path == "/api/separate":
                if not STATE["song_wav"]:
                    return self._json({"error": "Chưa có bài hát"}, 400)
                mode = (self._body_json() or {}).get("mode", "ai")
                song_wav, duration = STATE["song_wav"], STATE["duration"]
                out = os.path.join(WORK, "inst.wav")

                def job(cb):
                    if mode == "fast":
                        media.center_cut(song_wav, out, cb, duration)
                    else:
                        mdx.separate_mdx(song_wav, out, progress_cb=cb)
                    STATE.update(inst_wav=out, inst_mode=mode)
                    return {"mode": mode}
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("separate", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang tách beat dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            elif path == "/api/lrc":
                raw = self._body()
                if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                    text = raw.decode("utf-16", errors="replace")
                elif raw.startswith(b"\xef\xbb\xbf"):
                    text = raw.decode("utf-8-sig", errors="replace")
                else:
                    text = raw.decode("utf-8", errors="replace")
                lines = lyr.parse_lrc(text)
                if not lines:
                    return self._json({"error": "Không đọc được mốc giờ nào trong file .lrc"}, 400)
                self._json({"lines": lines})

            elif path == "/api/auto-align":
                if not STATE["song_wav"]:
                    return self._json({"error": "Chưa có bài hát"}, 400)
                req = self._body_json()
                texts = req.get("lines")
                if not isinstance(texts, list) or not texts:
                    return self._json({"error": "Chưa có lời để căn"}, 400)
                texts = [str(t).strip() for t in texts]
                if any(not t for t in texts) or len(texts) > 600:
                    return self._json(
                        {"error": "Lời có dòng trống hoặc quá nhiều câu"}, 400)
                song_wav, duration = STATE["song_wav"], STATE["duration"]
                models_dir = os.path.join(ROOT, "models")

                def job(cb):
                    from karaoke import align as alg
                    heard = alg.transcribe_words(song_wav, duration, cb,
                                                  models_dir)
                    full = alg.align_full(heard, texts, duration)
                    lines = [{"text": t, "start": s,
                              "words": [list(x) for x in ws]}
                             for t, s, ws in zip(texts, full["starts"],
                                                 full["words"])]
                    return {"lines": lines, "matched": full["ratio"],
                            "heard": len(heard)}
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("align", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang tự căn dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            elif path == "/api/render":
                req = self._body_json()
                lines = req.get("lines") or []
                if not isinstance(lines, list) or not lines:
                    return self._json({"error": "Chưa có lời đã căn nhịp"}, 400)
                for idx, ln in enumerate(lines):
                    if not isinstance(ln, dict) or not isinstance(ln.get("text"), str) \
                            or not ln["text"].strip():
                        return self._json({"error": f"Câu {idx + 1} thiếu lời"}, 400)
                    s = ln.get("start")
                    if isinstance(s, bool) or not isinstance(s, (int, float)):
                        return self._json(
                            {"error": f"Câu {idx + 1} chưa có giờ bắt đầu — "
                                       "căn nhịp trước khi xuất video"}, 400)
                style = req.get("style") or {}
                try:
                    guide = float(req.get("guide") or 0)
                except (TypeError, ValueError):
                    guide = 0.0
                bg_req = req.get("bg") or {"type": "color", "value": "#0b0e1a"}
                use_inst = req.get("audio", "inst") == "inst" and STATE["inst_wav"]
                base_audio = STATE["inst_wav"] if use_inst else STATE["song_wav"]
                if not base_audio:
                    return self._json({"error": "Chưa có nhạc"}, 400)
                duration = STATE["duration"]
                if duration <= 0:
                    return self._json(
                        {"error": "Không đọc được thời lượng bài hát"}, 400)
                timed = lyr.assign_ends(lines, duration)
                ass_path = os.path.join(WORK, "lyrics.ass")
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(lyr.build_ass(timed, style))
                bg = self._resolve_bg(bg_req)
                out_mp4 = os.path.join(WORK, "karaoke.mp4")
                song_wav = STATE["song_wav"]

                def job(cb):
                    audio = base_audio
                    if use_inst and guide > 0:
                        mixed = os.path.join(WORK, "mixed.wav")
                        media.mix_with_guide(base_audio, song_wav, guide, mixed)
                        audio = mixed
                    media.render_video(bg, audio, ass_path, out_mp4, duration, cb)
                    STATE["out_mp4"] = out_mp4
                    return {"video": "/api/video"}
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("render", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang xuất video dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            elif path == "/api/auto-all":
                # TỰ ĐỘNG TOÀN PHẦN: tách beat -> nghe & chép lời -> gắn mốc
                # giờ từng câu/từ -> xuất video, trong MỘT tác vụ duy nhất.
                if not STATE["song_wav"]:
                    return self._json({"error": "Chưa có bài hát"}, 400)
                req = self._body_json()
                texts = req.get("lyrics")
                if isinstance(texts, list):
                    texts = [str(t).strip() for t in texts if str(t).strip()]
                    if not texts:
                        texts = None  # không dán lời -> AI tự chép
                else:
                    texts = None
                if texts and len(texts) > 600:
                    return self._json({"error": "Quá nhiều câu lời"}, 400)
                sep_mode = "fast" if req.get("sep_mode") == "fast" else "ai"
                style = req.get("style") or {}
                title = str(req.get("title") or "").strip() or os.path.splitext(
                    STATE["song_name"] or "Karaoke")[0]
                try:
                    guide = float(req.get("guide") or 0)
                except (TypeError, ValueError):
                    guide = 0.0
                bg = self._resolve_bg(req.get("bg")
                                      or {"type": "gradient", "value": "demtim"})
                song_wav, duration = STATE["song_wav"], STATE["duration"]
                if duration <= 0:
                    return self._json(
                        {"error": "Không đọc được thời lượng bài hát"}, 400)
                models_dir = os.path.join(ROOT, "models")
                inst_out = os.path.join(WORK, "inst.wav")
                ass_path = os.path.join(WORK, "lyrics.ass")
                out_mp4 = os.path.join(WORK, "karaoke.mp4")

                def job(cb):
                    def scaled(lo, hi):
                        return lambda p, label="": cb(
                            lo + (hi - lo) * float(p) / 100.0, label)
                    cb(1, "Đang tách beat...")
                    if sep_mode == "fast":
                        media.center_cut(song_wav, inst_out, scaled(2, 30),
                                         duration)
                    else:
                        mdx.separate_mdx(song_wav, inst_out,
                                         progress_cb=scaled(2, 30))
                    STATE.update(inst_wav=inst_out, inst_mode=sep_mode)
                    from karaoke import align as alg
                    segs = alg.transcribe_segments(song_wav, duration,
                                                   scaled(32, 68), models_dir)
                    cb(70, "Đang gắn mốc giờ từng câu...")
                    if texts:
                        heard = [w for s in segs for w in s["words"]]
                        full = alg.align_full(heard, texts, duration)
                        raw = [{"text": t, "start": s,
                                "words": [list(x) for x in ws]}
                               for t, s, ws in zip(texts, full["starts"],
                                                   full["words"])]
                        matched, source = full["ratio"], "user"
                    else:
                        raw = alg.segments_to_lines(segs)
                        matched, source = 1.0, "ai"
                    if not raw:
                        raise ValueError(
                            "Không tạo được lời từ bài này — thử dán lời vào "
                            "bước 3 rồi bấm Tự căn bằng AI")
                    timed = lyr.assign_ends(raw, duration)
                    st = dict(style)
                    if title:
                        st["title"] = title
                    with open(ass_path, "w", encoding="utf-8") as f:
                        f.write(lyr.build_ass(timed, st))
                    cb(80, "Đang xuất video...")
                    audio = inst_out
                    if guide > 0:
                        mixed = os.path.join(WORK, "mixed.wav")
                        media.mix_with_guide(inst_out, song_wav, guide, mixed)
                        audio = mixed
                    media.render_video(bg, audio, ass_path, out_mp4, duration,
                                       scaled(80, 100))
                    STATE["out_mp4"] = out_mp4
                    return {"video": "/api/video", "lines": timed,
                            "matched": matched, "source": source,
                            "count": len(timed)}
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("autoall", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang làm video tự động dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": str(e)}, 500)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"Karaoke Maker đang chạy tại {url}")
    if os.environ.get("KARAOKE_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
