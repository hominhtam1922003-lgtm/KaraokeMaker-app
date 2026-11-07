"""Karaoke Maker — app PC: tách beat AI, căn nhịp lời, xuất video karaoke.

Ruột xử lý chạy native trên máy (máy chủ local 127.0.0.1 + FFmpeg + model AI);
vỏ hiển thị ưu tiên CỬA SỔ APP RIÊNG (pywebview), không mở được mới lùi về
trình duyệt. Đóng gói thành .exe bằng PyInstaller (xem KaraokeMaker.spec).
"""
import json
import os
import queue
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

def new_ctx(workdir):
    """Một ngữ cảnh làm việc độc lập (thư mục riêng + trạng thái riêng) —
    phiên chính dùng STATE/WORK, mỗi bài trong hàng loạt dùng ctx riêng để
    chạy song song không giẫm file của nhau."""
    os.makedirs(workdir, exist_ok=True)
    return {
        "_work": workdir,
        "song_name": None,
        "song_wav": None,       # WAV làm việc trích từ file gốc
        "duration": 0.0,
        "inst_wav": None,       # WAV beat đã tách
        "inst_mode": None,
        "bg_image": None,
        "bg_video": None,
        "out_mp4": None,
    }


STATE = new_ctx(WORK)
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


ACTIVE = {"separate": None, "render": None, "align": None, "autoall": None,
          "autolink": None}


def any_job_running():
    """Có bất kỳ tác vụ nền nào đang chạy không — các tác vụ ghi chung bộ file
    trong thư mục session nên phải chạy lần lượt, không song song."""
    with LOCK:
        return any((JOBS.get(ACTIVE.get(k) or "") or {}).get("status") == "running"
                   for k in ACTIVE)


def _scaled(cb, lo, hi):
    """Bọc callback tiến độ: ánh xạ 0-100 của một công đoạn vào [lo, hi]
    của toàn trình (để thanh tiến độ chạy liền mạch qua nhiều công đoạn)."""
    return lambda p, label="": cb(lo + (hi - lo) * float(p) / 100.0, label)


def _load_song_file(ctx, src, name):
    """Nạp một file nguồn làm bài hát của ctx: trích WAV làm việc trong thư
    mục của ctx. Trả về thời lượng (giây)."""
    wav = os.path.join(ctx["_work"], "song.wav")
    media.extract_audio(src, wav)
    ctx.update(song_name=name, song_wav=wav,
               duration=media.probe_duration(wav),
               inst_wav=None, inst_mode=None, out_mp4=None)
    return ctx["duration"]


_WHISPER_LOCK = threading.Lock()
_WHISPER_READY = False


def _ensure_whisper(models_dir):
    """Nạp/tải model Whisper MỘT lần dưới khoá — nhiều bài chạy song song
    không được tải trùng (tránh hỏng file model khi tải dở cùng lúc)."""
    global _WHISPER_READY
    if _WHISPER_READY:
        return
    with _WHISPER_LOCK:
        if _WHISPER_READY:
            return
        from karaoke import align as alg
        alg.load_model_only(models_dir)
        _WHISPER_READY = True


def resolve_bg(bg_req, ctx):
    """Chọn nền video từ yêu cầu: ảnh/video đã có trong ctx, mẫu gradient
    sẵn có (tạo ảnh trong thư mục của ctx), hoặc màu trơn."""
    bg_req = bg_req or {}
    t = bg_req.get("type")
    if t == "image" and ctx.get("bg_image"):
        return {"type": "image", "value": ctx["bg_image"]}
    if t == "video" and ctx.get("bg_video"):
        return {"type": "video", "value": ctx["bg_video"]}
    if t == "gradient":
        kind = str(bg_req.get("value") or "demtim")
        path = os.path.join(ctx["_work"], f"grad_{kind}.png")
        if not os.path.exists(path):
            media.make_gradient_bg(kind, path)
        return {"type": "image", "value": path}
    return {"type": "color", "value": bg_req.get("value", "#0b0e1a")}


def run_pipeline(cb, ctx, texts, sep_mode, style, title, guide, bg,
                 video_url="/api/video"):
    """TOÀN TRÌNH TỰ HÀNH trên bài hát đã nạp trong ctx: tách beat -> nghe &
    chép lời -> gắn mốc giờ từng câu/từ -> xuất video. texts=None nghĩa là
    để AI tự chép lời; có texts thì đối chiếu lời đó. Trả về dict kết quả."""
    work = ctx["_work"]
    song_wav, duration = ctx["song_wav"], ctx["duration"]
    models_dir = os.path.join(ROOT, "models")
    inst_out = os.path.join(work, "inst.wav")
    ass_path = os.path.join(work, "lyrics.ass")
    out_mp4 = os.path.join(work, "karaoke.mp4")
    cb(1, "Đang tách beat...")
    if sep_mode == "fast":
        media.center_cut(song_wav, inst_out, _scaled(cb, 2, 30), duration)
    else:
        mdx.separate_mdx(song_wav, inst_out, progress_cb=_scaled(cb, 2, 30))
    ctx.update(inst_wav=inst_out, inst_mode=sep_mode)
    _ensure_whisper(models_dir)
    from karaoke import align as alg
    segs = alg.transcribe_segments(song_wav, duration, _scaled(cb, 32, 68),
                                   models_dir)
    cb(70, "Đang gắn mốc giờ từng câu...")
    if texts:
        heard = [w for s in segs for w in s["words"]]
        full = alg.align_full(heard, texts, duration)
        raw = [{"text": t, "start": s, "words": [list(x) for x in ws]}
               for t, s, ws in zip(texts, full["starts"], full["words"])]
        matched, source = full["ratio"], "user"
    else:
        raw = alg.segments_to_lines(segs)
        matched, source = 1.0, "ai"
    if not raw:
        raise ValueError(
            "Không tạo được lời từ bài này — thử dán lời vào bước 3 rồi "
            "bấm Tự căn bằng AI")
    timed = lyr.assign_ends(raw, duration)
    st = dict(style)
    if title:
        st["title"] = title
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(lyr.build_ass(timed, st))
    cb(80, "Đang xuất video...")
    audio = inst_out
    if guide > 0:
        mixed = os.path.join(work, "mixed.wav")
        media.mix_with_guide(inst_out, song_wav, guide, mixed)
        audio = mixed
    media.render_video(bg, audio, ass_path, out_mp4, duration,
                       _scaled(cb, 80, 100))
    ctx["out_mp4"] = out_mp4
    return {"video": video_url, "lines": timed, "matched": matched,
            "source": source, "count": len(timed)}


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


# ---------------- HÀNG LOẠT (batch): nhiều link, chạy song song ----------------
BATCH = {}            # id -> item công khai + "_ctx" nội bộ
BATCH_ORDER = []      # thứ tự hiển thị
BATCH_QUEUE = queue.Queue()
_BATCH_WORKERS = False
BATCH_MAX_LINKS = 20
BATCH_PARALLEL = 2    # số bài chạy cùng lúc (AI ăn CPU — 2 là vừa máy thường)


def _batch_public(item):
    return {k: item[k] for k in ("id", "url", "title", "status", "progress",
                                 "label", "error")}


def _run_batch_item(item, opts):
    """Một bài trong hàng loạt: tải YouTube -> nạp -> toàn trình -> video,
    tất cả trong thư mục riêng của bài đó."""
    ctx = item["_ctx"]

    def cb(pct, label=""):
        with LOCK:
            item["progress"] = round(float(pct), 1)
            if label:
                item["label"] = label
    from karaoke import ytdl
    fb = media.ffmpeg_bin()
    ffmpeg_dir = os.path.dirname(os.path.abspath(fb)) \
        if os.path.sep in fb else None
    src, yt_title, video_path = ytdl.download(
        item["url"], ctx["_work"], _scaled(cb, 2, 16),
        opts["want_video"], ffmpeg_dir)
    with LOCK:
        item["title"] = yt_title
    dur = _load_song_file(ctx, src, yt_title)
    if dur <= 0:
        raise ValueError("File tải về không đọc được tiếng — thử link khác")
    if video_path:
        ctx["bg_video"] = video_path
        bg = {"type": "video", "value": video_path}
    else:
        bg = resolve_bg(opts["bg"], ctx)
    run_pipeline(_scaled(cb, 18, 100), ctx, None, opts["sep_mode"],
                 opts["style"], yt_title, opts["guide"], bg,
                 video_url=f"/api/batch/{item['id']}/video")


def _batch_worker():
    while True:
        item_id, opts = BATCH_QUEUE.get()
        item = BATCH.get(item_id)
        if item is None:
            continue
        with LOCK:
            item["status"] = "running"
        try:
            _run_batch_item(item, opts)
            with LOCK:
                item.update(status="done", progress=100.0, label="Xong")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                item.update(status="error", error=str(e))


def _ensure_batch_workers():
    global _BATCH_WORKERS
    with LOCK:
        if _BATCH_WORKERS:
            return
        _BATCH_WORKERS = True
    for _ in range(BATCH_PARALLEL):
        threading.Thread(target=_batch_worker, daemon=True).start()


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
        return resolve_bg(bg_req, STATE)

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
            elif path == "/api/batch":
                with LOCK:
                    items = [_batch_public(BATCH[i]) for i in BATCH_ORDER
                             if i in BATCH]
                self._json({"items": items})
            elif path.startswith("/api/batch/"):
                parts = path.split("/")  # /api/batch/<id>/video|download
                item = BATCH.get(parts[3]) if len(parts) == 5 else None
                out = item["_ctx"]["out_mp4"] if item else None
                if not out or not os.path.exists(out):
                    return self._json(
                        {"error": "Bài này chưa có video"}, 404)
                if parts[4] == "download":
                    safe = "".join(c for c in (item["title"] or "karaoke")
                                   if c not in '<>:"/\\|?*').strip()[:80]
                    serve_file(self, out, "video/mp4",
                               download_name=(safe or "karaoke") + ".mp4")
                elif parts[4] == "video":
                    serve_file(self, out, "video/mp4")
                else:
                    self._json({"error": "not found"}, 404)
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
                dur = _load_song_file(STATE, src, name)
                self._json({"ok": True, "name": name, "duration": dur})

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
                if STATE["duration"] <= 0:
                    return self._json(
                        {"error": "Không đọc được thời lượng bài hát"}, 400)

                def job(cb):
                    return run_pipeline(cb, STATE, texts, sep_mode, style,
                                        title, guide, bg)
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("autoall", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang làm video tự động dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            elif path == "/api/auto-link":
                # HỆ THỐNG TỰ HÀNH: link YouTube -> tải -> nạp bài -> toàn
                # trình tự động -> video karaoke hoàn chỉnh, MỘT tác vụ.
                req = self._body_json()
                from karaoke import ytdl
                url = str(req.get("url") or "").strip()
                try:
                    ytdl.canonical_url(url)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                want_video = bool(req.get("want_video"))
                texts = req.get("lyrics")
                if isinstance(texts, list):
                    texts = [str(t).strip() for t in texts if str(t).strip()]
                    if not texts:
                        texts = None
                else:
                    texts = None
                if texts and len(texts) > 600:
                    return self._json({"error": "Quá nhiều câu lời"}, 400)
                sep_mode = "fast" if req.get("sep_mode") == "fast" else "ai"
                style = req.get("style") or {}
                title_req = str(req.get("title") or "").strip()
                try:
                    guide = float(req.get("guide") or 0)
                except (TypeError, ValueError):
                    guide = 0.0
                fallback_bg = self._resolve_bg(
                    req.get("bg") or {"type": "gradient", "value": "demtim"})
                fb = media.ffmpeg_bin()
                ffmpeg_dir = os.path.dirname(os.path.abspath(fb)) \
                    if os.path.sep in fb else None

                def job(cb):
                    src, yt_title, video_path = ytdl.download(
                        url, WORK, _scaled(cb, 2, 16), want_video, ffmpeg_dir)
                    dur = _load_song_file(STATE, src, yt_title)
                    if dur <= 0:
                        raise ValueError(
                            "File tải về không đọc được tiếng — thử link khác")
                    if video_path:
                        STATE["bg_video"] = video_path
                    bg = ({"type": "video", "value": video_path}
                          if video_path else fallback_bg)
                    return run_pipeline(_scaled(cb, 18, 100), STATE, texts,
                                        sep_mode, style,
                                        title_req or yt_title, guide, bg)
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"}, 409)
                jid = start_job("autolink", job)
                if jid is None:
                    return self._json(
                        {"error": "Đang chạy tự hành dở — chờ xong đã"}, 409)
                self._json({"job": jid})

            elif path == "/api/batch":
                # HÀNG LOẠT: nhiều link YouTube -> mỗi bài một thư mục riêng,
                # chạy song song (tối đa BATCH_PARALLEL bài), xong bài nào
                # tải bài đó. Link hỏng thành mục lỗi hiển thị rõ, không nuốt.
                req = self._body_json()
                urls = req.get("urls")
                if not isinstance(urls, list) or not urls:
                    return self._json(
                        {"error": "Chưa có link nào — dán ít nhất 1 link "
                                  "YouTube"}, 400)
                urls = [str(u).strip() for u in urls if str(u).strip()]
                if not urls:
                    return self._json({"error": "Danh sách link rỗng"}, 400)
                if len(urls) > BATCH_MAX_LINKS:
                    return self._json(
                        {"error": f"Tối đa {BATCH_MAX_LINKS} link mỗi đợt — "
                                   "chia nhỏ ra nhé"}, 400)
                from karaoke import ytdl
                sep_mode = "fast" if req.get("sep_mode") == "fast" else "ai"
                try:
                    guide = float(req.get("guide") or 0)
                except (TypeError, ValueError):
                    guide = 0.0
                bg_req = req.get("bg") \
                    or {"type": "gradient", "value": "demtim"}
                if (bg_req or {}).get("type") not in ("gradient", "color"):
                    bg_req = {"type": "gradient", "value": "demtim"}
                opts = {"want_video": bool(req.get("want_video")),
                        "sep_mode": sep_mode,
                        "style": req.get("style") or {},
                        "guide": guide, "bg": bg_req}
                _ensure_batch_workers()
                created, first_err = [], None
                for raw_url in urls:
                    iid = uuid.uuid4().hex[:10]
                    item = {"id": iid, "url": raw_url, "title": None,
                            "status": "queued", "progress": 0.0, "label": "",
                            "error": None,
                            "_ctx": new_ctx(os.path.join(ROOT, "batch", iid))}
                    try:
                        item["url"] = ytdl.canonical_url(raw_url)
                    except ValueError as e:
                        item.update(status="error", error=str(e))
                        first_err = first_err or str(e)
                    with LOCK:
                        BATCH[iid] = item
                        BATCH_ORDER.append(iid)
                    created.append(iid)
                    if item["status"] == "queued":
                        BATCH_QUEUE.put((iid, opts))
                if not any(BATCH[i]["status"] == "queued" for i in created):
                    return self._json(
                        {"error": first_err or "Không có link nào hợp lệ"},
                        400)
                self._json({"items": created})

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
    print(f"Karaoke Maker đang chạy tại {url}", flush=True)
    if os.environ.get("KARAOKE_NO_BROWSER") == "1":
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    # Ưu tiên CỬA SỔ APP RIÊNG trên máy (pywebview/WebView2). Mở không được
    # vì bất kỳ lý do gì thì lùi về trình duyệt như cũ — vỏ hiển thị không
    # bao giờ được làm chết app.
    try:
        import webview
        threading.Thread(target=server.serve_forever, daemon=True).start()
        webview.create_window("Karaoke Maker — làm video karaoke", url,
                              width=1280, height=860, min_size=(960, 640))
        webview.start()
        return
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--whisper-worker":
        # Chế độ worker Whisper (tiến trình con, xem karaoke/whisper_worker.py)
        from karaoke.whisper_worker import main as _worker_main
        sys.exit(_worker_main(sys.argv[2:]))
    main()
