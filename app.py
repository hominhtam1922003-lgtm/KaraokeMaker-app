"""Karaoke Maker — app PC: tách beat AI, căn nhịp lời, xuất video karaoke.

Ruột xử lý chạy native trên máy (máy chủ local 127.0.0.1 + FFmpeg + model AI);
vỏ hiển thị ưu tiên CỬA SỔ APP RIÊNG (pywebview), không mở được mới lùi về
trình duyệt. Đóng gói thành .exe bằng PyInstaller (xem KaraokeMaker.spec).
"""
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "4.1.0"

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
# v4: tầng DỰ ÁN — mỗi bài là một project lưu bền trong thư mục riêng.
# Project "default" chính là phiên session cũ (thư mục WORK) để mọi luồng
# v3 chạy y nguyên; các project khác nằm ở PROJECTS_DIR/<id>/.
PROJECTS_DIR = os.path.join(ROOT, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)
PRESETS_FILE = os.path.join(ROOT, "presets.json")

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


def _ensure_whisper(models_dir, progress_cb=None):
    """Nạp/tải model Whisper MỘT lần dưới khoá — nhiều bài chạy song song
    không được tải trùng (tránh hỏng file model khi tải dở cùng lúc).
    Tiến độ tải được chuyển tiếp ra ngoài (bản cũ nuốt mất, người dùng
    nhìn thanh phần trăm đứng im suốt mấy phút tải 470 MB)."""
    global _WHISPER_READY
    if _WHISPER_READY:
        return
    with _WHISPER_LOCK:
        if _WHISPER_READY:
            return
        from karaoke import align as alg
        alg.load_model_only(models_dir, progress_cb)
        _WHISPER_READY = True


RATIOS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


def style_render_opts(style):
    """Dịch dict phong cách từ giao diện thành (style cho ASS đã gắn sẵn
    PlayRes theo tỉ lệ khung, kích thước render, có thanh tiến trình).
    style['size'] = [w, h] ghi đè tỉ lệ (hàng đợi xuất dùng cho preset 4K)."""
    st = dict(style or {})
    raw_size = st.get("size")
    if isinstance(raw_size, (list, tuple)) and len(raw_size) == 2:
        try:
            size = (max(16, int(raw_size[0])), max(16, int(raw_size[1])))
        except (TypeError, ValueError):
            size = RATIOS.get(str(st.get("ratio") or "16:9"), (1920, 1080))
    else:
        size = RATIOS.get(str(st.get("ratio") or "16:9"), (1920, 1080))
    st["play_x"], st["play_y"] = size
    return st, size, bool(st.get("progress_bar"))


def resolve_bg(bg_req, ctx, size=(1920, 1080)):
    """Chọn nền video từ yêu cầu: ảnh/video đã có trong ctx, mẫu gradient
    sẵn có (tĩnh hoặc ĐỘNG, tạo trong thư mục của ctx theo đúng tỉ lệ
    khung), hoặc màu trơn."""
    bg_req = bg_req or {}
    t = bg_req.get("type")
    if t == "image" and ctx.get("bg_image"):
        return {"type": "image", "value": ctx["bg_image"]}
    if t == "video" and ctx.get("bg_video"):
        return {"type": "video", "value": ctx["bg_video"]}
    if t == "gradient":
        kind = str(bg_req.get("value") or "demtim")
        path = os.path.join(ctx["_work"], f"grad_{kind}_{size[0]}x{size[1]}.png")
        if not os.path.exists(path):
            media.make_gradient_bg(kind, path, size)
        return {"type": "image", "value": path}
    if t == "gradient_anim":
        kind = str(bg_req.get("value") or "demtim")
        path = os.path.join(ctx["_work"],
                            f"gradanim_{kind}_{size[0]}x{size[1]}.mp4")
        if not os.path.exists(path):
            small = (720, 1280) if size[1] > size[0] else \
                ((1080, 1080) if size[0] == size[1] else (1280, 720))
            media.make_gradient_video(kind, path, 30, small)
        return {"type": "video", "value": path}
    return {"type": "color", "value": bg_req.get("value", "#0b0e1a")}


def _require_bg_resolved(bg_req, resolved):
    """Nền ảnh/video user ĐÃ CHỌN mà không tìm thấy file thì lỗi rõ ràng —
    tuyệt đối không lặng lẽ rơi về nền màu tối khi xuất (job/hàng đợi báo
    lỗi, người dùng tải lại file nền là xong)."""
    t = (bg_req or {}).get("type")
    if t in ("image", "video") and resolved.get("type") != t:
        raise ValueError(
            "Chưa tìm thấy file nền " +
            ("ảnh" if t == "image" else "video") +
            " đã chọn — mở Studio, tải lại file nền rồi thử lại")


# Xem trước nền: WebView2/Chromium chỉ phát được các codec/container này.
_WEB_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
_WEB_VIDEO_EXTS = {".mp4", ".m4v", ".webm", ".mov"}
_BG_VIDEO_CTYPES = {".mp4": "video/mp4", ".m4v": "video/mp4",
                     ".webm": "video/webm", ".mov": "video/quicktime"}
_BG_IMAGE_CTYPES = {".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".webp": "image/webp",
                    ".gif": "image/gif", ".bmp": "image/bmp"}
_BG_PREVIEW_LOCK = threading.Lock()


def _video_codec(path):
    """codec_name của stream video đầu tiên; '' nếu không đọc được."""
    try:
        cmd = [media.ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_name", "-of", "csv=p=0", path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           **media.no_window_kwargs())
        lines = (r.stdout or "").strip().splitlines()
        return lines[0].strip() if lines else ""
    except Exception:  # noqa: BLE001
        return ""


def _bg_preview_file(src):
    """File PHỤC VỤ XEM TRƯỚC cho video nền: trả thẳng file gốc nếu
    WebView2 phát được; định dạng lạ (HEVC, mpeg4, mkv...) thì chuyển mã
    một bản H.264 nhẹ đặt cạnh file gốc (cache theo mtime+size của gốc).
    Bản XUẤT luôn dùng file gốc qua ffmpeg — bản này chỉ để xem trước.
    Trả None nếu chuyển mã cũng hỏng (server sẽ phát gốc, client báo rõ).
    """
    ext = os.path.splitext(src)[1].lower()
    if ext in _WEB_VIDEO_EXTS and _video_codec(src) in _WEB_VIDEO_CODECS:
        return src
    workdir = os.path.dirname(src)
    dst = os.path.join(workdir, "bg_preview.mp4")
    stamp = os.path.join(workdir, "bg_preview.src")
    try:
        key = f"{os.path.getmtime(src)}:{os.path.getsize(src)}"
    except OSError:
        return None
    with _BG_PREVIEW_LOCK:
        try:
            with open(stamp, encoding="utf-8") as f:
                if f.read().strip() == key and os.path.exists(dst):
                    return dst
        except Exception:  # noqa: BLE001
            pass
        tmp = dst + ".tmp.mp4"
        cmd = [media.ffmpeg_bin(), "-y", "-v", "error", "-i", src,
               "-an", "-vf", "scale=min(960\\,iw):-2",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp]
        r = subprocess.run(cmd, capture_output=True, timeout=600,
                           **media.no_window_kwargs())
        if r.returncode != 0 or not os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None
        os.replace(tmp, dst)
        try:
            with open(stamp, "w", encoding="utf-8") as f:
                f.write(key)
        except Exception:  # noqa: BLE001
            pass
        return dst


def _drop_bg_preview(workdir):
    """Xoá cache xem trước (khi user đổi video nền khác)."""
    for name in ("bg_preview.mp4", "bg_preview.src"):
        try:
            os.remove(os.path.join(workdir, name))
        except OSError:
            pass


def _ass_dialogue_count(ass_text):
    """Số sự kiện Dialogue trong bản ASS — 0 nghĩa là video sẽ TRƠN chữ."""
    return (ass_text or "").count("Dialogue:")


def _require_ass_events(ass_text, burn=True):
    """Đốt chữ mà bản ASS không có câu nào = chắc chắn ra video trơn.
    Chặn ngay tại chỗ — không để khâu render 'thành công giả'."""
    if burn and _ass_dialogue_count(ass_text) <= 0:
        raise ValueError(
            "Bản chữ karaoke không có câu nào để đốt — kiểm tra lại lời "
            "và mốc giờ rồi thử lại (không xuất video trơn)")


def _frame_rgb(mp4, at_sec, width=480):
    """Giải mã 1 khung của MP4 thành mảng RGB (numpy) — phục vụ cổng kiểm
    sau xuất. None nếu không giải mã được."""
    import numpy as np
    cmd = [media.ffmpeg_bin(), "-v", "error",
           "-ss", f"{max(0.0, at_sec):.2f}", "-i", mp4,
           "-frames:v", "1", "-vf", f"scale={width}:-2",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=120,
                       **media.no_window_kwargs())
    if r.returncode != 0 or not r.stdout or len(r.stdout) % (width * 3):
        return None
    h = len(r.stdout) // (width * 3)
    if h <= 0:
        return None
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(h, width, 3)


def _hex_rgb(value):
    s = str(value or "").lstrip("#")
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def verify_export_text(mp4, timed, style):
    """CỔNG KIỂM SAU XUẤT (mọi đường xuất có đốt chữ đều qua): trích khung
    ở giữa câu đầu/giữa/cuối từ chính file MP4 vừa xuất, đếm pixel mang
    màu chữ của style (đã hát / chưa hát / song ca) hoặc gần trắng trong
    dải chữ nửa dưới khung. Không khung nào đạt ngưỡng -> video coi như
    KHÔNG có chữ: ném lỗi để job báo lỗi thay vì báo 'xong' oan (sự cố
    máy thật 07/11/2026: xuất 'xong' mà video trơn chữ + sai nền)."""
    import numpy as np
    lines = [ln for ln in (timed or [])
             if ln.get("start") is not None and (ln.get("text") or "").strip()]
    if not lines:
        raise RuntimeError(
            "Không có câu lời nào có mốc giờ để kiểm tra video đầu ra")
    colors = []
    for key in ("color", "base_color", "duet_color",
                "duet_female_color", "duet_male_color"):
        rgb = _hex_rgb((style or {}).get(key))
        if rgb and rgb not in colors:
            colors.append(rgb)
    picks = []
    for idx in sorted({0, len(lines) // 2, len(lines) - 1}):
        ln = lines[idx]
        s = float(ln["start"])
        e = float(ln.get("end") or s + 2.0)
        # Hai thời điểm trong câu (45% và 75%): tránh mốc rơi vào hiệu
        # ứng mờ dần ở đầu/cuối câu.
        picks.append(s + 0.45 * max(0.4, e - s))
        picks.append(s + 0.75 * max(0.4, e - s))
    checked = 0
    for at in picks:
        frame = _frame_rgb(mp4, at)
        if frame is None:
            continue
        checked += 1
        h = frame.shape[0]
        band = frame[int(h * 0.5):, :, :].astype(int)
        total = band.shape[0] * band.shape[1]
        hit = np.zeros(band.shape[:2], dtype=bool)
        for rgb in colors:
            hit |= (np.abs(band - np.array(rgb)).max(axis=2) <= 42)
        mx = band.max(axis=2)
        mn = band.min(axis=2)
        hit |= (mn >= 195) & ((mx - mn) <= 45)
        # Ngưỡng THẤP có chủ đích: câu ngắn (vài chữ) trên khung lớn chỉ
        # cho ~100 pixel chữ ở khung mẫu 480px (đo thật ca H2: 98–115px,
        # trong khi video trơn trên nền phẳng cho ~0px). Cổng này là
        # lưới thứ hai sau cổng đếm sự kiện ASS — bắt thảm hoạ "đốt mà
        # không ra chữ", không thay thế kiểm bằng mắt.
        if int(hit.sum()) >= max(30, int(total * 0.0008)):
            return
    if checked == 0:
        raise RuntimeError(
            "Không trích được khung hình nào từ video vừa xuất để kiểm "
            "tra chữ — coi như chưa đạt, thử xuất lại")
    raise RuntimeError(
        "Video xuất ra KHÔNG thấy chữ karaoke ở các mốc có câu hát — "
        "khâu đốt chữ có thể đã hỏng. Đã chặn, không báo 'xong' oan; "
        "thử xuất lại hoặc kiểm tra lại lời/mốc giờ")


def _vocal_rms(wav_path, t0, t1):
    """RMS tín hiệu trong [t0, t1) đo trên PCM 16k mono của file WAV.
    None = không đo được (miễn kiểm — không chặn oan)."""
    try:
        import numpy as np
        pcm = str(wav_path) + ".gate.pcm"
        media.decode_pcm16k(str(wav_path), pcm)
        try:
            a = np.fromfile(pcm, dtype=np.float32)
        finally:
            try:
                os.remove(pcm)
            except OSError:
                pass
        if a.size == 0:
            return None
        sr = 16000
        seg = a[int(max(0.0, t0) * sr):int(max(0.0, t1) * sr)]
        if seg.size == 0:
            return None
        return float(np.sqrt(np.mean(seg.astype(np.float64) ** 2)))
    except Exception:  # noqa: BLE001
        return None


def _check_lyric_lines(lines, duration, vocal_wav=None):
    """TỰ KIỂM lời sau khi căn giờ, TRƯỚC khi xuất (đường AI tự chép):
    - mốc giờ phải nằm trong thời lượng bài;
    - câu đầu bắt đầu quá trễ (>25% bài) MÀ stem giọng đo được tiếng hát
      rõ trong 25% đầu -> AI đã bỏ sót phần đầu: lỗi rõ ràng, không xuất
      lặng lẽ ra video thiếu lời nửa bài (sự cố máy thật 07/11/2026)."""
    if not lines or not duration or duration <= 0:
        return
    starts = [float(ln["start"]) for ln in lines
              if ln.get("start") is not None]
    if not starts:
        raise ValueError("Không câu nào có mốc giờ — không xuất được")
    if min(starts) < -0.01 or max(starts) > duration + 1.0:
        raise ValueError(
            "Mốc giờ lời nằm ngoài thời lượng bài — căn giờ đã hỏng, "
            "thử Tự căn lại hoặc căn tay bằng Space")
    first = min(starts)
    if duration >= 40 and first > duration * 0.25 and vocal_wav:
        rms = _vocal_rms(vocal_wav, 0.0, duration * 0.25)
        if rms is not None and rms >= 0.015:
            raise ValueError(
                f"AI không chép được lời ở phần đầu bài (câu đầu tiên "
                f"chỉ bắt đầu ở {int(first // 60)}:{int(first % 60):02d}) "
                "dù đoạn đầu có tiếng hát — xuất ra sẽ thiếu lời nửa "
                "bài. Đường chuẩn: dán lời bài hát rồi bấm 'Tự căn nhịp "
                "bằng AI', hoặc gắn nhịp tay bằng Space")


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
    from karaoke import align as alg
    cb(1, "Đang chuẩn bị...")
    _ensure_whisper(models_dir, _scaled(cb, 2, 8))
    vocal_out = os.path.join(work, "vocal.wav")
    gate_wav = None  # stem giọng (nếu có) cho cổng kiểm thiếu lời phần đầu
    if texts or sep_mode == "fast":
        # Có lời dán sẵn (chỉ cần mốc giờ từng từ trên bản phối) hoặc chế độ
        # nhanh (không có stem giọng): tách beat và nghe lời là hai việc
        # ĐỘC LẬP — chạy SONG SONG, tiến độ trộn theo trọng số để thanh %
        # chạy một mạch, không nhảy lùi.
        frac = {"sep": 0.0, "wh": 0.0}
        frac_lock = threading.Lock()

        def combined_cb(which):
            def _cb(p, label=""):
                with frac_lock:
                    frac[which] = max(frac[which],
                                      min(100.0, max(0.0, float(p))) / 100.0)
                    total = 8 + 66 * (0.45 * frac["sep"] + 0.55 * frac["wh"])
                cb(total, label)
            return _cb

        sep_err = {}

        def do_sep():
            try:
                if sep_mode == "fast":
                    media.center_cut(song_wav, inst_out, combined_cb("sep"),
                                     duration)
                else:
                    mdx.separate_mdx(song_wav, inst_out,
                                     progress_cb=combined_cb("sep"))
            except Exception as e:  # noqa: BLE001
                sep_err["e"] = e

        sep_thread = threading.Thread(target=do_sep, daemon=True)
        sep_thread.start()
        segs = alg.transcribe_segments(song_wav, duration, combined_cb("wh"),
                                       models_dir)
        sep_thread.join()
        if "e" in sep_err:
            raise sep_err["e"]
    else:
        # AI TỰ CHÉP LỜI + tách AI: nghe trên STEM GIỌNG HÁT đã tách riêng
        # (hết tiếng nhạc đè -> đỡ sai chính tả hẳn so với nghe bản phối).
        # Đánh đổi: hai bước chạy nối tiếp thay vì song song.
        mdx.separate_mdx(song_wav, inst_out,
                         progress_cb=_scaled(cb, 8, 40),
                         vocal_out=vocal_out)
        hear_src = vocal_out if os.path.exists(vocal_out) else song_wav
        if hear_src == vocal_out:
            gate_wav = vocal_out
        segs = alg.transcribe_segments(hear_src, duration,
                                       _scaled(cb, 40, 74), models_dir)
    ctx.update(inst_wav=inst_out, inst_mode=sep_mode)
    cb(76, "Đang gắn mốc giờ từng câu...")
    if texts:
        heard = [w for s in segs for w in s["words"]]
        full = alg.align_full(heard, texts, duration)
        line_ok = full.get("line_ok") or []
        raw = [{"text": t, "start": s, "words": [list(x) for x in ws],
                "ok": bool(line_ok[i]) if i < len(line_ok) else True}
               for i, (t, s, ws) in enumerate(
                   zip(texts, full["starts"], full["words"]))]
        matched, source = full["ratio"], "user"
    else:
        raw = [{**ln, "ok": True} for ln in alg.segments_to_lines(segs)]
        matched, source = 1.0, "ai"
    if not raw:
        raise ValueError(
            "Không tạo được lời từ bài này — thử dán lời vào bước 3 rồi "
            "bấm Tự căn bằng AI")
    timed = lyr.assign_ends(raw, duration)
    if source == "ai":
        _check_lyric_lines(timed, duration, gate_wav)
    st, size, bar = style_render_opts(style)
    if title:
        st["title"] = title
    ass_text = lyr.build_ass(timed, st)
    _require_ass_events(ass_text)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)
    cb(80, "Đang xuất video...")
    audio = inst_out
    if guide > 0:
        mixed = os.path.join(work, "mixed.wav")
        media.mix_with_guide(inst_out, song_wav, guide, mixed)
        audio = mixed
    media.render_video(bg, audio, ass_path, out_mp4, duration,
                       _scaled(cb, 80, 100), size=size, progress_bar=bar)
    verify_export_text(out_mp4, timed, st)
    ctx["out_mp4"] = out_mp4
    result = {"video": video_url, "lines": timed, "matched": matched,
              "source": source, "count": len(timed)}
    if source == "ai":
        # User chốt 07/11: lời chuẩn là lời DÁN + AI căn giờ; lời tự chép
        # chỉ là BẢN NHÁP — phải nói rõ ngay trong kết quả, không để ai
        # tưởng đây là lời chuẩn.
        result["warning"] = (
            "Đang dùng lời AI TỰ CHÉP (bản nháp) — AI nghe hát hay sai "
            "chữ. Muốn lời chuẩn: dán lời bài hát rồi bấm 'Tự căn nhịp "
            "bằng AI'")
    return result


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


SAVE_DIR = os.path.join(os.path.expanduser("~"), "Videos", "KaraokeMaker")


def _safe_name(s, fallback="karaoke"):
    safe = "".join(c for c in (s or "") if c not in '<>:"/\\|?*').strip()[:80]
    return safe or fallback


def _save_video_copy(src_mp4, title):
    """Chép video thành phẩm vào thư mục Videos\\KaraokeMaker của người
    dùng (nơi dễ tìm, mở bằng trình phát thường) — nút tải trình duyệt
    không hoạt động trong cửa sổ app WebView2 nên đây là đường chính."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    dst = os.path.join(SAVE_DIR, _safe_name(title) + ".mp4")
    if os.path.abspath(src_mp4) != os.path.abspath(dst):
        shutil.copyfile(src_mp4, dst)
    return dst


def _batch_public(item):
    out = {k: item[k] for k in ("id", "url", "title", "status", "progress",
                                "label", "error")}
    out["kind"] = item.get("kind", "link")
    out["project_id"] = item.get("project_id")
    return out


def _run_batch_item(item, opts):
    """Một bài trong hàng loạt: (tải YouTube | dùng file sẵn) -> nạp ->
    toàn trình -> video, tất cả trong thư mục riêng của bài đó."""
    ctx = item["_ctx"]

    def cb(pct, label=""):
        with LOCK:
            item["progress"] = round(float(pct), 1)
            if label:
                item["label"] = label
    if item.get("kind") == "file":
        src = item["_src"]
        yt_title = item["title"] or "Karaoke"
        video_path = None
        cb(10, "Đang đọc file...")
        dur = _load_song_file(ctx, src, yt_title)
        if dur <= 0:
            raise ValueError("File không đọc được tiếng — thử file khác")
        try:
            os.remove(src)
        except OSError:
            pass
        bg = resolve_bg(opts["bg"], ctx,
                        style_render_opts(opts.get("style"))[1])
        _require_bg_resolved(opts["bg"], bg)
        return run_pipeline(_scaled(cb, 18, 100), ctx, None, opts["sep_mode"],
                            opts["style"], yt_title, opts["guide"], bg,
                            video_url=f"/api/batch/{item['id']}/video")
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
        bg = resolve_bg(opts["bg"], ctx,
                        style_render_opts(opts.get("style"))[1])
        _require_bg_resolved(opts["bg"], bg)
    return run_pipeline(_scaled(cb, 18, 100), ctx, None, opts["sep_mode"],
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
            res = _run_batch_item(item, opts)
            # v4: bài hàng loạt xong -> thành PROJECT bền trong Thư viện
            # (mở lại/sửa tiếp/xuất lại được). Lỗi tạo project không được
            # làm hỏng kết quả hàng loạt.
            try:
                ctx = item["_ctx"]
                pid = _materialize_project(
                    item["title"] or "Karaoke", ctx["_work"],
                    (res or {}).get("lines"), opts.get("style"),
                    opts.get("bg"), opts.get("guide"),
                    {"kind": item.get("kind", "link"),
                     "url": item.get("url")},
                    opts.get("sep_mode"), ctx["duration"],
                    ctx["song_name"])
                with LOCK:
                    item["project_id"] = pid
            except Exception:  # noqa: BLE001
                traceback.print_exc()
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


# ---------------- v4: TẦNG DỰ ÁN (project) ----------------
# Mỗi bài = 1 project: thư mục riêng chứa file làm việc + project.json
# (tiêu đề, nguồn, dòng lời + mốc + giọng, style, nền, trạng thái). Phiên
# session cũ chính là project "default" (thư mục WORK) — STATE luôn trỏ
# vào project đang mở, nên toàn bộ endpoint v3 chạy y nguyên trên project
# hiện hành; mở project khác = trỏ STATE sang thư mục của project đó.
CURRENT = {"id": "default"}
_PID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _project_dir(pid):
    pid = str(pid or "")
    if pid == "default":
        return WORK
    if not pid or len(pid) > 40 or any(c not in _PID_OK for c in pid):
        raise ValueError("Mã project không hợp lệ")
    return os.path.join(PROJECTS_DIR, pid)


def _project_json_path(pid):
    return os.path.join(_project_dir(pid), "project.json")


def _load_project_json(pid):
    """Đọc project.json -> (data, corrupt). File chưa có -> ({}, False);
    file HỎNG (JSON gãy) -> ({}, True) để giao diện báo rõ thay vì nuốt."""
    try:
        with open(_project_json_path(pid), encoding="utf-8") as f:
            data = json.load(f)
        return (data if isinstance(data, dict) else {}), False
    except FileNotFoundError:
        return {}, False
    except Exception:  # noqa: BLE001
        return {}, True


def _save_project_json(pid, data):
    pdir = _project_dir(pid)
    os.makedirs(pdir, exist_ok=True)
    tmp = os.path.join(pdir, "project.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _project_json_path(pid))


def _sanitize_lines(raw):
    """Chuẩn hoá danh sách dòng lời từ client/lưu trữ: giữ text/start/end/
    words/voice/ok, ép kiểu an toàn. Dòng không phải dict -> bỏ qua."""
    out = []
    for ln in raw or []:
        if not isinstance(ln, dict):
            continue
        text = str(ln.get("text") or "")
        start = ln.get("start")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            start = None
        end = ln.get("end")
        if isinstance(end, bool) or not isinstance(end, (int, float)):
            end = None
        words = None
        if isinstance(ln.get("words"), list) and ln["words"]:
            words = []
            for wt in ln["words"]:
                try:
                    if isinstance(wt, dict):
                        words.append([float(wt["start"]), float(wt["end"])])
                    else:
                        words.append([float(wt[0]), float(wt[1])])
                except Exception:  # noqa: BLE001
                    words = None
                    break
        item = {"text": text,
                "start": None if start is None else round(float(start), 3),
                "end": None if end is None else round(float(end), 3),
                "words": words}
        if ln.get("voice") in ("f", "m"):
            item["voice"] = ln["voice"]
        if ln.get("ok") is not None:
            item["ok"] = bool(ln["ok"])
        out.append(item)
    return out[:600]


def _lyrics_status(lines):
    if not lines:
        return "none"
    if any(l.get("start") is None for l in lines):
        return "draft"
    return "synced"


def _project_ctx(pid):
    """Dựng ctx làm việc của project từ file trên đĩa + project.json."""
    pdir = _project_dir(pid)
    data, _corrupt = _load_project_json(pid)
    ctx = new_ctx(pdir)
    sw = os.path.join(pdir, "song.wav")
    if os.path.exists(sw):
        ctx["song_wav"] = sw
        ctx["song_name"] = data.get("song_name")
        dur = data.get("duration")
        ctx["duration"] = float(dur) if isinstance(dur, (int, float)) \
            and not isinstance(dur, bool) and dur > 0 \
            else media.probe_duration(sw)
    iw = os.path.join(pdir, "inst.wav")
    if os.path.exists(iw):
        ctx["inst_wav"] = iw
        ctx["inst_mode"] = data.get("inst_mode")
    for key in ("bg_image", "bg_video"):
        hits = glob.glob(os.path.join(pdir, key + ".*"))
        if hits:
            # File MỚI NHẤT thắng: thư mục có thể còn file nền cũ khác đuôi
            # (từ trước khi upload biết tự dọn) — không để file cũ đè nền
            # user vừa chọn khi xuất.
            ctx[key] = max(hits, key=lambda p: os.path.getmtime(p))
    om = os.path.join(pdir, "karaoke.mp4")
    if os.path.exists(om):
        ctx["out_mp4"] = om
    return ctx, data


def _project_summary(pid):
    ctx, data = _project_ctx(pid)
    _d, corrupt = _load_project_json(pid)
    lines = _sanitize_lines(data.get("lines") or [])
    style = data.get("style") or {}
    bg = data.get("bg") or {}
    return {
        "id": pid,
        "title": data.get("title") or data.get("song_name")
                 or ("Phiên làm việc hiện tại" if pid == "default"
                     else "Dự án mới"),
        "song_name": data.get("song_name"),
        "duration": ctx["duration"],
        "created": data.get("created"),
        "updated": data.get("updated"),
        "source_kind": (data.get("source") or {}).get("kind"),
        "has_song": bool(ctx["song_wav"]),
        "inst_mode": ctx["inst_mode"],
        "ratio": str(style.get("ratio") or "16:9"),
        "grad": bg.get("value") if bg.get("type") in (
            "gradient", "gradient_anim") else None,
        "status": {
            "beat": bool(ctx["inst_wav"]),
            "lyrics": _lyrics_status(lines),
            "exported": bool(data.get("exported") or ctx["out_mp4"]),
        },
        "corrupt": corrupt,
    }


def _list_project_ids():
    ids = ["default"]
    if os.path.isdir(PROJECTS_DIR):
        for name in sorted(os.listdir(PROJECTS_DIR)):
            if os.path.isdir(os.path.join(PROJECTS_DIR, name)):
                ids.append(name)
    return ids


def _mark_project(pid, **fields):
    """Ghi bổ sung vào project.json — bookkeeping phụ, lỗi thì bỏ qua để
    không bao giờ làm hỏng tác vụ chính đang chạy."""
    try:
        data, _c = _load_project_json(pid)
        data.update(fields)
        data["updated"] = time.time()
        _save_project_json(pid, data)
    except Exception:  # noqa: BLE001
        pass


def _mark_current_project(**fields):
    _mark_project(CURRENT["id"], **fields)


def _project_payload(pid):
    ctx, data = _project_ctx(pid)
    return {
        "project": _project_summary(pid),
        "lines": _sanitize_lines(data.get("lines") or []),
        "style": data.get("style") or {},
        "bg": data.get("bg") or {"type": "gradient", "value": "demtim"},
        "guide": data.get("guide") or 0,
        "lyrics_text": data.get("lyrics_text") or "",
        "duration": ctx["duration"],
        "song_name": ctx["song_name"],
        "inst_ready": bool(ctx["inst_wav"]),
        "has_video": bool(ctx["out_mp4"]),
    }


def _activate_project(pid):
    """Mở project: trỏ STATE (phiên làm việc) sang thư mục của project.
    Các endpoint v3 dùng STATE['_work'] nên tự chạy trên project mới."""
    ctx, _data = _project_ctx(pid)
    STATE.clear()
    STATE.update(ctx)
    CURRENT["id"] = pid
    return _project_payload(pid)


def _materialize_project(title, src_dir, lines, style, bg, guide, source,
                         inst_mode, duration, song_name):
    """Tạo project bền từ một thư mục làm việc tạm (kết quả hàng loạt):
    chép các file cốt lõi sang thư mục project + ghi project.json."""
    pid = uuid.uuid4().hex[:10]
    pdir = os.path.join(PROJECTS_DIR, pid)
    os.makedirs(pdir, exist_ok=True)
    for fname in ("song.wav", "inst.wav", "vocal.wav", "karaoke.mp4",
                  "lyrics.ass"):
        src = os.path.join(src_dir, fname)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(pdir, fname))
    for pat in ("bg_image.*", "bg_video.*"):
        for hit in glob.glob(os.path.join(src_dir, pat)):
            shutil.copyfile(hit, os.path.join(pdir, os.path.basename(hit)))
    now = time.time()
    data = {"id": pid, "title": title, "song_name": song_name,
            "duration": duration, "inst_mode": inst_mode,
            "lines": _sanitize_lines(lines or []),
            "style": style or {}, "bg": bg or {}, "guide": guide or 0,
            "source": source or {}, "exported": True,
            "created": now, "updated": now}
    _save_project_json(pid, data)
    return pid


def _compute_peaks(audio_path, n):
    """Peaks waveform: giải mã mono 22050Hz bằng ffmpeg rồi lấy biên độ
    cực đại từng bucket, chuẩn hoá 0..1. File im lặng -> toàn 0 (không
    sập); file ngắn -> ít mẫu vẫn chia bucket bình thường."""
    import numpy as np
    n = max(24, min(int(n or 240), 1200))
    cmd = [media.ffmpeg_bin(), "-v", "error", "-i", audio_path,
           "-ac", "1", "-ar", "22050", "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=180,
                       **media.no_window_kwargs())
    if r.returncode != 0 or not r.stdout:
        return []
    a = np.abs(np.frombuffer(r.stdout, dtype="<i2").astype(np.float32)
               / 32768.0)
    if a.size == 0:
        return []
    n = min(n, int(a.size))
    edges = np.linspace(0, a.size, n + 1).astype(int)
    peaks = [float(a[edges[i]:edges[i + 1]].max())
             if edges[i + 1] > edges[i] else 0.0 for i in range(n)]
    top = max(peaks) if peaks else 0.0
    if top > 0:
        peaks = [p / top for p in peaks]
    return [round(p, 3) for p in peaks]


def _project_peaks(pid, src_kind, n):
    """Peaks của project (src: song|inst), cache theo mtime+size+n."""
    ctx, _data = _project_ctx(pid)
    path = ctx["inst_wav"] if src_kind == "inst" else ctx["song_wav"]
    if not path or not os.path.exists(path):
        return None
    n = max(24, min(int(n or 240), 1200))
    st = os.stat(path)
    key = f"{st.st_mtime_ns}:{st.st_size}:{n}:{src_kind}"
    cache = os.path.join(ctx["_work"], f"peaks_{src_kind}_{n}.json")
    try:
        with open(cache, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("key") == key:
            return {"duration": ctx["duration"],
                    "peaks": saved.get("peaks") or []}
    except Exception:  # noqa: BLE001
        pass
    peaks = _compute_peaks(path, n)
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"key": key, "peaks": peaks}, f)
    except Exception:  # noqa: BLE001
        pass
    return {"duration": ctx["duration"], "peaks": peaks}


# ---------------- v4: MẪU CẤU HÌNH (preset) ----------------

def _load_presets():
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_presets(items):
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


# ---------------- v4: HÀNG ĐỢI XUẤT (export queue) ----------------
# Khác hàng loạt (batch = làm trọn quy trình từ link/file): hàng đợi xuất
# chỉ RENDER các project đã có lời, lần lượt từng bài, lưu thẳng file ra
# thư mục đích với preset định dạng/encoder/chất lượng đã chọn.
EXPORT_FORMATS = {
    "yt": {"label": "YouTube · 16:9", "ratio": "16:9",
           "size": (1920, 1080)},
    "shorts": {"label": "Shorts / TikTok · 9:16", "ratio": "9:16",
               "size": (1080, 1920)},
    "fb": {"label": "Facebook · 1:1", "ratio": "1:1",
           "size": (1080, 1080)},
    "yt4k": {"label": "YouTube 4K · 16:9", "ratio": "16:9",
             "size": (3840, 2160)},
}
QUALITY_KBPS = {"cao": 16000, "vua": 10000, "thap": 6000}
EXPORTQ = {}
EXPORTQ_ORDER = []
EXPORT_QUEUE = queue.Queue()
_EXPORT_WORKER = False


def _export_public(it):
    return {k: it.get(k) for k in (
        "id", "project_id", "title", "format", "status", "progress",
        "label", "error", "saved_path", "size_bytes", "encoder")}


def _resolve_encoder(want):
    if want == "nvenc":
        return "nvenc"
    if want == "cpu":
        return "cpu"
    return "nvenc" if media.has_nvenc() else "cpu"


def _run_export_item(item):
    cfg = item["config"]
    pid = item["project_id"]
    ctx, data = _project_ctx(pid)
    if not ctx["song_wav"]:
        raise ValueError("Project chưa có bài hát")
    lines = _sanitize_lines(data.get("lines") or [])
    if not lines:
        raise ValueError("Project chưa có lời — mở Studio căn lời trước")
    missing = sum(1 for l in lines if l.get("start") is None)
    if missing:
        raise ValueError(f"Còn {missing} câu chưa căn nhịp — mở Studio "
                         "căn nốt trước khi xuất")
    duration = ctx["duration"]
    if duration <= 0:
        raise ValueError("Không đọc được thời lượng bài hát")
    timed = lyr.assign_ends(lines, duration)
    style = dict(data.get("style") or {})
    fmt = EXPORT_FORMATS[cfg["format"]]
    style["ratio"] = fmt["ratio"]
    style["size"] = list(fmt["size"])
    st, size, bar = style_render_opts(style)
    pdir = ctx["_work"]
    ass_path = os.path.join(pdir, "lyrics.ass")
    ass_text = lyr.build_ass(timed, st)
    _require_ass_events(ass_text, burn=cfg.get("burn", True))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_text)
    bg = resolve_bg(data.get("bg") or {"type": "gradient", "value": "demtim"},
                    ctx, size)
    _require_bg_resolved(data.get("bg"), bg)
    audio = ctx["inst_wav"] or ctx["song_wav"]
    try:
        guide = float(data.get("guide") or 0)
    except (TypeError, ValueError):
        guide = 0.0
    if ctx["inst_wav"] and guide > 0:
        mixed = os.path.join(pdir, "mixed.wav")
        media.mix_with_guide(ctx["inst_wav"], ctx["song_wav"], guide, mixed)
        audio = mixed
    out_dir = str(cfg.get("out_dir") or SAVE_DIR)
    os.makedirs(out_dir, exist_ok=True)
    base = _safe_name(cfg.get("filename") or item["title"], "karaoke")
    out_mp4 = os.path.join(out_dir, base + ".mp4")
    k = 2
    while os.path.exists(out_mp4):
        out_mp4 = os.path.join(out_dir, f"{base} ({k}).mp4")
        k += 1

    def cb(p, label=""):
        with LOCK:
            item["progress"] = round(float(p), 1)
            if label:
                item["label"] = label
    used = media.render_video(
        bg, audio, ass_path if cfg.get("burn", True) else None,
        out_mp4, duration, cb, size=size, progress_bar=bar,
        encoder=_resolve_encoder(cfg.get("encoder") or "auto"),
        bitrate_k=QUALITY_KBPS.get(cfg.get("quality") or "cao"),
        bg_blur=style.get("bg_blur") or 0)
    if cfg.get("burn", True):
        try:
            verify_export_text(out_mp4, timed, st)
        except Exception:
            # Video không đạt cổng kiểm: xoá khỏi thư mục lưu của user,
            # không để file hỏng nằm đó như một sản phẩm "đã xong".
            try:
                os.remove(out_mp4)
            except OSError:
                pass
            raise
    if cfg.get("export_ass"):
        shutil.copyfile(ass_path, os.path.splitext(out_mp4)[0] + ".ass")
    proj_mp4 = os.path.join(pdir, "karaoke.mp4")
    if os.path.abspath(out_mp4) != os.path.abspath(proj_mp4):
        shutil.copyfile(out_mp4, proj_mp4)
    if CURRENT["id"] == pid:
        STATE["out_mp4"] = proj_mp4
    _mark_project(pid, exported=True,
                  last_export={"file": out_mp4, "encoder": used,
                               "at": time.time()})
    item.update(saved_path=out_mp4,
                size_bytes=os.path.getsize(out_mp4), encoder=used)


def _export_worker():
    while True:
        iid = EXPORT_QUEUE.get()
        item = EXPORTQ.get(iid)
        if item is None:
            continue
        with LOCK:
            item.update(status="running", progress=0.0,
                        label="Đang xuất...")
        try:
            _run_export_item(item)
            with LOCK:
                item.update(status="done", progress=100.0, label="Xong")
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                item.update(status="error", error=str(e))


def _ensure_export_worker():
    global _EXPORT_WORKER
    with LOCK:
        if _EXPORT_WORKER:
            return
        _EXPORT_WORKER = True
    threading.Thread(target=_export_worker, daemon=True).start()


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

    def _resolve_bg(self, bg_req, style=None):
        return resolve_bg(bg_req, STATE, style_render_opts(style)[1])

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
            elif path == "/api/bg-preview":
                # Phát đúng file nền của phiên hiện tại (STATE đi theo
                # project đang mở) — cùng một file mà khâu xuất sẽ dùng.
                qs = urllib.parse.parse_qs(parsed.query)
                kind = (qs.get("kind") or ["video"])[0]
                if kind == "image":
                    src = STATE["bg_image"]
                    if not src or not os.path.exists(src):
                        return self._json(
                            {"error": "Chưa có ảnh nền — hãy tải ảnh nền "
                                      "trước"}, 404)
                    serve_file(self, src, _BG_IMAGE_CTYPES.get(
                        os.path.splitext(src)[1].lower(),
                        "application/octet-stream"))
                else:
                    src = STATE["bg_video"]
                    if not src or not os.path.exists(src):
                        return self._json(
                            {"error": "Chưa có video nền — hãy tải video "
                                      "nền trước"}, 404)
                    serve = _bg_preview_file(src) or src
                    serve_file(self, serve, _BG_VIDEO_CTYPES.get(
                        os.path.splitext(serve)[1].lower(), "video/mp4"))
            elif path == "/api/download" and STATE["out_mp4"]:
                serve_file(self, STATE["out_mp4"], "video/mp4",
                           download_name="karaoke.mp4")
            elif path == "/api/download-inst" and STATE["inst_wav"]:
                serve_file(self, STATE["inst_wav"], "audio/wav",
                           download_name="beat.wav")
            elif path == "/api/batch":
                with LOCK:
                    items = [_batch_public(BATCH[i]) for i in BATCH_ORDER
                             if i in BATCH]
                self._json({"items": items})
            elif path.startswith("/api/batch/"):
                parts = path.split("/")  # /api/batch/<id>/video|download|...
                item = BATCH.get(parts[3]) if len(parts) == 5 else None
                if len(parts) == 5 and parts[4] == "download-inst":
                    inst = item["_ctx"]["inst_wav"] if item else None
                    if not inst or not os.path.exists(inst):
                        return self._json(
                            {"error": "Bài này chưa có beat"}, 404)
                    return serve_file(self, inst, "audio/wav",
                                      download_name="beat.wav")
                out = item["_ctx"]["out_mp4"] if item else None
                if not out or not os.path.exists(out):
                    return self._json(
                        {"error": "Bài này chưa có video"}, 404)
                if parts[4] == "download":
                    serve_file(self, out, "video/mp4",
                               download_name=_safe_name(item["title"]) + ".mp4")
                elif parts[4] == "video":
                    serve_file(self, out, "video/mp4")
                else:
                    self._json({"error": "not found"}, 404)
            elif path == "/api/app-info":
                self._json({"version": VERSION, "save_dir": SAVE_DIR,
                            "current_project": CURRENT["id"]})
            elif path == "/api/projects":
                items = []
                for pid in _list_project_ids():
                    try:
                        items.append(_project_summary(pid))
                    except Exception:  # noqa: BLE001
                        items.append({"id": pid, "title": pid,
                                      "corrupt": True,
                                      "status": {"beat": False,
                                                 "lyrics": "none",
                                                 "exported": False}})
                items.sort(key=lambda x: -(x.get("updated") or 0))
                try:
                    du = shutil.disk_usage(ROOT)
                    storage = {"total": du.total, "free": du.free}
                except Exception:  # noqa: BLE001
                    storage = {"total": 0, "free": 0}
                used = 0
                for pid in _list_project_ids():
                    try:
                        pdir = _project_dir(pid)
                        for f in glob.glob(os.path.join(pdir, "*")):
                            if os.path.isfile(f):
                                used += os.path.getsize(f)
                    except Exception:  # noqa: BLE001
                        pass
                storage["projects_bytes"] = used
                self._json({"items": items, "storage": storage,
                            "current": CURRENT["id"]})
            elif path == "/api/project/current":
                self._json(_project_payload(CURRENT["id"]))
            elif path.startswith("/api/projects/") and \
                    path.endswith("/peaks"):
                parts = path.split("/")
                pid = parts[3] if len(parts) == 5 else None
                qs = urllib.parse.parse_qs(parsed.query)
                src = (qs.get("src") or ["song"])[0]
                try:
                    n = int((qs.get("n") or ["240"])[0])
                except ValueError:
                    n = 240
                try:
                    res = _project_peaks(pid, src, n) if pid else None
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if res is None:
                    return self._json(
                        {"error": "Project chưa có file nhạc để vẽ sóng"},
                        404)
                self._json(res)
            elif path == "/api/presets":
                self._json({"items": _load_presets()})
            elif path == "/api/export/info":
                self._json({"nvenc": media.has_nvenc(),
                            "gpu": media.gpu_name(),
                            "formats": {k: {"label": v["label"],
                                            "size": list(v["size"])}
                                        for k, v in EXPORT_FORMATS.items()},
                            "save_dir": SAVE_DIR})
            elif path == "/api/export/queue":
                with LOCK:
                    items = [_export_public(EXPORTQ[i])
                             for i in EXPORTQ_ORDER if i in EXPORTQ]
                self._json({"items": items})
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
                src = os.path.join(STATE["_work"], "song_src" + ext)
                with open(src, "wb") as f:
                    f.write(payload)
                dur = _load_song_file(STATE, src, name)
                _mark_current_project(song_name=name, duration=dur,
                                      title=None, lines=[], lyrics_text="",
                                      exported=False, inst_mode=None)
                self._json({"ok": True, "name": name, "duration": dur})

            elif path in ("/api/upload-bg-image", "/api/upload-bg-video"):
                payload = self._body()
                if not payload:
                    return self._json({"error": "File rỗng — chưa chọn file?"}, 400)
                name = urllib.parse.unquote(
                    self.headers.get("X-File-Name") or "bg.bin")
                ext = os.path.splitext(name)[1] or ".bin"
                key = "bg_image" if path.endswith("image") else "bg_video"
                # Dọn file nền cũ cùng loại (kể cả khác đuôi): không dọn
                # thì trong thư mục tồn tại 2 ứng viên và khâu xuất có
                # thể nhặt lại file cũ thay vì nền user vừa chọn.
                for old in glob.glob(os.path.join(STATE["_work"], key + ".*")):
                    try:
                        os.remove(old)
                    except OSError:
                        pass
                if key == "bg_video":
                    _drop_bg_preview(STATE["_work"])
                dst = os.path.join(STATE["_work"], key + ext)
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
                out = os.path.join(STATE["_work"], "inst.wav")

                def job(cb):
                    if mode == "fast":
                        media.center_cut(song_wav, out, cb, duration)
                    else:
                        mdx.separate_mdx(song_wav, out, progress_cb=cb)
                    STATE.update(inst_wav=out, inst_mode=mode)
                    _mark_current_project(inst_mode=mode)
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
                    # Đã tách AI trước đó (có vocal.wav) thì nghe mốc từng
                    # từ trên STEM GIỌNG: sạch tiếng nhạc đè, mốc chuẩn
                    # hơn nghe trên bản phối.
                    vocal = os.path.join(STATE["_work"], "vocal.wav")
                    hear = vocal if os.path.exists(vocal) else song_wav
                    heard = alg.transcribe_words(hear, duration, cb,
                                                  models_dir)
                    full = alg.align_full(heard, texts, duration)
                    line_ok = full.get("line_ok") or []
                    lines = [{"text": t, "start": s,
                              "words": [list(x) for x in ws],
                              "ok": bool(line_ok[i]) if i < len(line_ok)
                                    else True}
                             for i, (t, s, ws) in enumerate(
                                 zip(texts, full["starts"], full["words"]))]
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
                st, size, bar = style_render_opts(style)
                workdir = STATE["_work"]
                ass_path = os.path.join(workdir, "lyrics.ass")
                ass_text = lyr.build_ass(timed, st)
                try:
                    _require_ass_events(ass_text)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_text)
                bg = self._resolve_bg(bg_req, style)
                try:
                    _require_bg_resolved(bg_req, bg)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                out_mp4 = os.path.join(workdir, "karaoke.mp4")
                song_wav = STATE["song_wav"]
                _mark_current_project(lines=_sanitize_lines(lines),
                                      style=style, bg=bg_req, guide=guide)

                def job(cb):
                    audio = base_audio
                    if use_inst and guide > 0:
                        mixed = os.path.join(workdir, "mixed.wav")
                        media.mix_with_guide(base_audio, song_wav, guide, mixed)
                        audio = mixed
                    media.render_video(bg, audio, ass_path, out_mp4, duration,
                                       cb, size=size, progress_bar=bar)
                    verify_export_text(out_mp4, timed, st)
                    STATE["out_mp4"] = out_mp4
                    _mark_current_project(exported=True)
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
                bg_req = req.get("bg") or {"type": "gradient",
                                           "value": "demtim"}
                bg = self._resolve_bg(bg_req, style)
                try:
                    _require_bg_resolved(bg_req, bg)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if STATE["duration"] <= 0:
                    return self._json(
                        {"error": "Không đọc được thời lượng bài hát"}, 400)

                def job(cb):
                    res = run_pipeline(cb, STATE, texts, sep_mode, style,
                                       title, guide, bg)
                    _mark_current_project(
                        lines=_sanitize_lines(res.get("lines")),
                        style=style, bg=req.get("bg"), guide=guide,
                        inst_mode=sep_mode, exported=True)
                    return res
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
                    req.get("bg") or {"type": "gradient", "value": "demtim"},
                    style)
                fb = media.ffmpeg_bin()
                ffmpeg_dir = os.path.dirname(os.path.abspath(fb)) \
                    if os.path.sep in fb else None

                def job(cb):
                    src, yt_title, video_path = ytdl.download(
                        url, STATE["_work"], _scaled(cb, 2, 16), want_video,
                        ffmpeg_dir)
                    dur = _load_song_file(STATE, src, yt_title)
                    if dur <= 0:
                        raise ValueError(
                            "File tải về không đọc được tiếng — thử link khác")
                    _mark_current_project(song_name=yt_title, duration=dur,
                                          title=None, exported=False)
                    if video_path:
                        STATE["bg_video"] = video_path
                    bg = ({"type": "video", "value": video_path}
                          if video_path else fallback_bg)
                    if not video_path:
                        _require_bg_resolved(req.get("bg"), fallback_bg)
                    res = run_pipeline(_scaled(cb, 18, 100), STATE, texts,
                                       sep_mode, style,
                                       title_req or yt_title, guide, bg)
                    _mark_current_project(
                        lines=_sanitize_lines(res.get("lines")),
                        style=style, guide=guide, inst_mode=sep_mode,
                        exported=True)
                    return res
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
                if (bg_req or {}).get("type") not in (
                        "gradient", "gradient_anim", "color"):
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
                            "kind": "link",
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

            elif path == "/api/batch-file":
                # HÀNG LOẠT TỪ FILE: một file nhạc/video có sẵn trên máy
                # được đưa vào hàng đợi chạy cùng opts của đợt hàng loạt
                # hiện tại (giao diện gửi kèm X-Batch-Opts dạng JSON).
                payload = self._body()
                if not payload:
                    return self._json(
                        {"error": "File rỗng — chưa chọn file?"}, 400)
                name = urllib.parse.unquote(
                    self.headers.get("X-File-Name") or "song.bin")
                try:
                    opts_req = json.loads(
                        self.headers.get("X-Batch-Opts") or "{}")
                except ValueError:
                    opts_req = {}
                sep_mode = "fast" if opts_req.get("sep_mode") == "fast" \
                    else "ai"
                try:
                    guide = float(opts_req.get("guide") or 0)
                except (TypeError, ValueError):
                    guide = 0.0
                bg_req = opts_req.get("bg") \
                    or {"type": "gradient", "value": "demtim"}
                if (bg_req or {}).get("type") not in (
                        "gradient", "gradient_anim", "color"):
                    bg_req = {"type": "gradient", "value": "demtim"}
                opts = {"want_video": False, "sep_mode": sep_mode,
                        "style": opts_req.get("style") or {},
                        "guide": guide, "bg": bg_req}
                _ensure_batch_workers()
                iid = uuid.uuid4().hex[:10]
                stage_dir = os.path.join(ROOT, "batch_uploads")
                os.makedirs(stage_dir, exist_ok=True)
                ext = os.path.splitext(name)[1] or ".bin"
                staged = os.path.join(stage_dir, iid + ext)
                with open(staged, "wb") as f:
                    f.write(payload)
                item = {"id": iid, "url": None,
                        "title": os.path.splitext(name)[0] or "Karaoke",
                        "kind": "file",
                        "status": "queued", "progress": 0.0, "label": "",
                        "error": None, "_src": staged,
                        "_ctx": new_ctx(os.path.join(ROOT, "batch", iid))}
                with LOCK:
                    BATCH[iid] = item
                    BATCH_ORDER.append(iid)
                BATCH_QUEUE.put((iid, opts))
                self._json({"item": iid})

            elif path == "/api/save-video":
                # Lưu video phiên chính vào Videos\KaraokeMaker (đường chính
                # thay nút tải — WebView2 không tải file qua thẻ <a>).
                if not STATE["out_mp4"] or not os.path.exists(STATE["out_mp4"]):
                    return self._json({"error": "Chưa có video để lưu"}, 400)
                title = os.path.splitext(STATE["song_name"] or "karaoke")[0]
                dst = _save_video_copy(STATE["out_mp4"], title)
                self._json({"ok": True, "path": dst})

            elif path.startswith("/api/batch/") and path.endswith("/save"):
                parts = path.split("/")  # /api/batch/<id>/save
                item = BATCH.get(parts[3]) if len(parts) == 5 else None
                out = item["_ctx"]["out_mp4"] if item else None
                if not out or not os.path.exists(out):
                    return self._json(
                        {"error": "Bài này chưa có video"}, 404)
                dst = _save_video_copy(out, item["title"])
                self._json({"ok": True, "path": dst})

            elif path == "/api/open-folder":
                # Chỉ mở đúng thư mục chứa video đã lưu — không mở đường
                # dẫn tùy ý từ yêu cầu.
                os.makedirs(SAVE_DIR, exist_ok=True)
                if sys.platform.startswith("win"):
                    os.startfile(SAVE_DIR)  # noqa: S606
                else:
                    try:
                        subprocess.Popen(["xdg-open", SAVE_DIR],
                                         **media.no_window_kwargs())
                    except OSError:
                        pass
                self._json({"ok": True, "path": SAVE_DIR})

            # ---------- v4: PROJECT ----------
            elif path == "/api/projects":
                req = self._body_json()
                title = str(req.get("title") or "").strip()[:120]
                pid = uuid.uuid4().hex[:10]
                now = time.time()
                _save_project_json(pid, {
                    "id": pid, "title": title or None, "lines": [],
                    "style": req.get("style") or {},
                    "bg": req.get("bg") or {"type": "gradient",
                                             "value": "demtim"},
                    "source": {"kind": "empty"}, "exported": False,
                    "created": now, "updated": now})
                self._json({"project": _project_summary(pid)})

            elif path == "/api/projects/import-file":
                payload = self._body()
                if not payload:
                    return self._json(
                        {"error": "File rỗng — chưa chọn file nhạc?"}, 400)
                name = urllib.parse.unquote(
                    self.headers.get("X-File-Name") or "song.bin")
                pid = uuid.uuid4().hex[:10]
                pdir = os.path.join(PROJECTS_DIR, pid)
                os.makedirs(pdir, exist_ok=True)
                ext = os.path.splitext(name)[1] or ".bin"
                src = os.path.join(pdir, "song_src" + ext)
                with open(src, "wb") as f:
                    f.write(payload)
                ctx = new_ctx(pdir)
                try:
                    dur = _load_song_file(ctx, src, name)
                    if dur <= 0:
                        raise ValueError("File không đọc được tiếng")
                except Exception as e:  # noqa: BLE001
                    shutil.rmtree(pdir, ignore_errors=True)
                    return self._json({"error": str(e)}, 400)
                now = time.time()
                _save_project_json(pid, {
                    "id": pid, "title": None, "song_name": name,
                    "duration": dur, "inst_mode": None, "lines": [],
                    "style": {}, "bg": {"type": "gradient",
                                        "value": "demtim"},
                    "source": {"kind": "file", "name": name},
                    "exported": False, "created": now, "updated": now})
                self._json({"project": _project_summary(pid)})

            elif path == "/api/projects/import-link":
                req = self._body_json()
                from karaoke import ytdl
                url = str(req.get("url") or "").strip()
                try:
                    url = ytdl.canonical_url(url)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                want_video = bool(req.get("want_video"))
                sep_mode = "fast" if req.get("sep_mode") == "fast" else "ai"
                style = req.get("style") or {}
                bg_req = req.get("bg") or {"type": "gradient",
                                           "value": "demtim"}
                pid = uuid.uuid4().hex[:10]
                pdir = os.path.join(PROJECTS_DIR, pid)
                ctx = new_ctx(pdir)
                now = time.time()
                _save_project_json(pid, {
                    "id": pid, "title": None, "lines": [], "style": style,
                    "bg": bg_req, "source": {"kind": "link", "url": url},
                    "exported": False, "created": now, "updated": now})
                fb = media.ffmpeg_bin()
                ffmpeg_dir = os.path.dirname(os.path.abspath(fb)) \
                    if os.path.sep in fb else None

                def job(cb):
                    src, yt_title, video_path = ytdl.download(
                        url, pdir, _scaled(cb, 2, 16), want_video, ffmpeg_dir)
                    dur = _load_song_file(ctx, src, yt_title)
                    if dur <= 0:
                        raise ValueError(
                            "File tải về không đọc được tiếng — thử link khác")
                    if video_path:
                        ctx["bg_video"] = video_path
                        bg = {"type": "video", "value": video_path}
                    else:
                        bg = resolve_bg(bg_req, ctx,
                                        style_render_opts(style)[1])
                    res = run_pipeline(_scaled(cb, 18, 100), ctx, None,
                                       sep_mode, style, yt_title, 0, bg)
                    _mark_project(pid, song_name=yt_title, duration=dur,
                                  lines=_sanitize_lines(res.get("lines")),
                                  inst_mode=sep_mode, exported=True)
                    return {"project": pid, "title": yt_title}
                jid = new_job(job)
                self._json({"job": jid, "project": pid})

            elif path.startswith("/api/projects/") and \
                    path.endswith("/open"):
                parts = path.split("/")
                pid = parts[3] if len(parts) == 5 else None
                try:
                    pdir = _project_dir(pid) if pid else None
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not pdir or not os.path.isdir(pdir):
                    return self._json({"error": "Không thấy project"}, 404)
                _d, corrupt = _load_project_json(pid)
                if corrupt:
                    return self._json(
                        {"error": "File project.json của project này bị "
                                  "hỏng — không mở được"}, 400)
                if any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong rồi "
                                  "mở project khác"}, 409)
                self._json(_activate_project(pid))

            elif path == "/api/project/current":
                req = self._body_json()
                data, corrupt = _load_project_json(CURRENT["id"])
                if corrupt:
                    return self._json(
                        {"error": "project.json của project đang mở bị "
                                  "hỏng — không lưu được"}, 400)
                if "title" in req:
                    data["title"] = str(req["title"] or "").strip()[:120] \
                        or None
                if "lines" in req:
                    data["lines"] = _sanitize_lines(req["lines"])
                if isinstance(req.get("style"), dict):
                    data["style"] = req["style"]
                if isinstance(req.get("bg"), dict):
                    data["bg"] = req["bg"]
                if "guide" in req:
                    try:
                        data["guide"] = max(0.0, min(
                            40.0, float(req["guide"])))
                    except (TypeError, ValueError):
                        pass
                if "lyrics_text" in req:
                    data["lyrics_text"] = str(req["lyrics_text"])[:100000]
                data["updated"] = time.time()
                _save_project_json(CURRENT["id"], data)
                self._json({"ok": True, "updated": data["updated"]})

            elif path.startswith("/api/projects/") and \
                    path.endswith("/delete"):
                parts = path.split("/")
                pid = parts[3] if len(parts) == 5 else None
                if pid == "default":
                    return self._json(
                        {"error": "Không xoá được project mặc định"}, 400)
                try:
                    pdir = _project_dir(pid) if pid else None
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not pdir or not os.path.isdir(pdir):
                    return self._json({"error": "Không thấy project"}, 404)
                if CURRENT["id"] == pid:
                    _activate_project("default")
                shutil.rmtree(pdir, ignore_errors=True)
                self._json({"ok": True})

            elif path.startswith("/api/projects/") and \
                    path.endswith("/separate"):
                parts = path.split("/")
                pid = parts[3] if len(parts) == 5 else None
                try:
                    pdir = _project_dir(pid) if pid else None
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not pdir or not os.path.isdir(pdir):
                    return self._json({"error": "Không thấy project"}, 404)
                if pid == CURRENT["id"] and any_job_running():
                    return self._json(
                        {"error": "Đang có tác vụ chạy dở — chờ xong đã"},
                        409)
                mode = (self._body_json() or {}).get("mode", "ai")
                ctx, _data = _project_ctx(pid)
                if not ctx["song_wav"]:
                    return self._json(
                        {"error": "Project chưa có bài hát"}, 400)
                song_wav, duration = ctx["song_wav"], ctx["duration"]
                out = os.path.join(pdir, "inst.wav")

                def job(cb):
                    if mode == "fast":
                        media.center_cut(song_wav, out, cb, duration)
                    else:
                        mdx.separate_mdx(song_wav, out, progress_cb=cb)
                    if CURRENT["id"] == pid:
                        STATE.update(inst_wav=out, inst_mode=mode)
                    _mark_project(pid, inst_mode=mode)
                    return {"mode": mode}
                jid = new_job(job)
                self._json({"job": jid})

            # ---------- v4: PRESET + HÀNG ĐỢI XUẤT ----------
            elif path == "/api/presets":
                req = self._body_json()
                name = str(req.get("name") or "").strip()[:60]
                if not name:
                    return self._json({"error": "Chưa đặt tên mẫu"}, 400)
                items = [p for p in _load_presets()
                         if p.get("name") != name]
                items.append({"name": name,
                              "style": req.get("style") or {},
                              "bg": req.get("bg") or {},
                              "export": req.get("export") or {},
                              "saved_at": time.time()})
                _save_presets(items)
                self._json({"ok": True, "items": items})

            elif path == "/api/presets/delete":
                name = str((self._body_json() or {}).get("name") or "")
                items = [p for p in _load_presets()
                         if p.get("name") != name]
                _save_presets(items)
                self._json({"ok": True, "items": items})

            elif path == "/api/export/queue":
                req = self._body_json()
                pid = str(req.get("project_id") or CURRENT["id"])
                try:
                    pdir = _project_dir(pid)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not os.path.isdir(pdir):
                    return self._json({"error": "Không thấy project"}, 404)
                _d, corrupt = _load_project_json(pid)
                if corrupt:
                    return self._json(
                        {"error": "project.json của project này bị hỏng"},
                        400)
                ctx, data = _project_ctx(pid)
                if not ctx["song_wav"]:
                    return self._json(
                        {"error": "Project chưa có bài hát"}, 400)
                qlines = _sanitize_lines(data.get("lines") or [])
                if not qlines:
                    return self._json(
                        {"error": "Project chưa có lời — mở Studio căn "
                                  "lời trước"}, 400)
                miss = sum(1 for l in qlines if l.get("start") is None)
                if miss:
                    return self._json(
                        {"error": f"Còn {miss} câu chưa căn nhịp — mở "
                                  "Studio căn nốt trước khi xuất"}, 400)
                cfg_in = req.get("config") or {}
                config = {
                    "format": cfg_in.get("format")
                              if cfg_in.get("format") in EXPORT_FORMATS
                              else "yt",
                    "encoder": cfg_in.get("encoder")
                               if cfg_in.get("encoder") in (
                                   "auto", "nvenc", "cpu") else "auto",
                    "quality": cfg_in.get("quality")
                               if cfg_in.get("quality") in QUALITY_KBPS
                               else "cao",
                    "burn": bool(cfg_in.get("burn", True)),
                    "export_ass": bool(cfg_in.get("export_ass")),
                    "out_dir": str(cfg_in.get("out_dir") or SAVE_DIR),
                    "filename": str(cfg_in.get("filename") or ""),
                }
                summary = _project_summary(pid)
                iid = uuid.uuid4().hex[:10]
                item = {"id": iid, "project_id": pid,
                        "title": summary["title"],
                        "format": EXPORT_FORMATS[config["format"]]["label"],
                        "status": "queued", "progress": 0.0, "label": "",
                        "error": None, "saved_path": None,
                        "size_bytes": None, "encoder": None,
                        "config": config}
                with LOCK:
                    EXPORTQ[iid] = item
                    EXPORTQ_ORDER.append(iid)
                _ensure_export_worker()
                EXPORT_QUEUE.put(iid)
                self._json({"item": iid})

            elif path.startswith("/api/export/queue/") and \
                    path.endswith("/remove"):
                parts = path.split("/")
                iid = parts[4] if len(parts) == 6 else None
                item = EXPORTQ.get(iid) if iid else None
                if not item:
                    return self._json({"error": "Không thấy mục xuất"}, 404)
                if item["status"] == "running":
                    return self._json(
                        {"error": "Đang xuất dở — không gỡ được"}, 409)
                with LOCK:
                    EXPORTQ.pop(iid, None)
                    if iid in EXPORTQ_ORDER:
                        EXPORTQ_ORDER.remove(iid)
                self._json({"ok": True})

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
    print(f"Karaoke Maker {VERSION} đang chạy tại {url}", flush=True)
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
        webview.create_window(f"Karaoke Maker {VERSION} — làm video karaoke",
                              url, width=1360, height=900,
                              min_size=(1024, 680))
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
