"""Xử lý media bằng FFmpeg: trích âm thanh, cắt giọng nhanh, trộn, xuất video."""
import json
import os
import re
import shutil
import subprocess
import sys


def no_window_kwargs():
    """Kwargs cho subprocess để tiến trình phụ KHÔNG bật cửa sổ console
    đen trên Windows (sự cố máy thật 07/11/2026: cửa sổ ffmpeg.exe nhảy
    lên che app). Nền tảng khác: rỗng."""
    if sys.platform.startswith("win"):
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def ffmpeg_bin():
    # Khi đóng gói bằng PyInstaller, ffmpeg nằm cạnh exe / trong bundle.
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"))
        candidates.append(os.path.join(sys._MEIPASS, "ffmpeg.exe"))
        candidates.append(os.path.join(sys._MEIPASS, "ffmpeg"))
    candidates.append(shutil.which("ffmpeg") or "ffmpeg")
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return candidates[-1]


def ffprobe_bin():
    ff = ffmpeg_bin()
    probe = ff.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe")
    if os.path.exists(probe):
        return probe
    return shutil.which("ffprobe") or "ffprobe"


def probe_duration(path):
    """Độ dài file (giây). File hỏng/không tồn tại/không đọc được -> 0.0."""
    try:
        cmd = [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
               "-of", "json", path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           **no_window_kwargs())
        data = json.loads(r.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def check_readable(path):
    """True nếu ffmpeg GIẢI MÃ THỬ được file (0.5 giây đầu / 1 khung ảnh).

    Chỉ hỏi ffprobe có stream hay không là KHÔNG đủ: file chữ bắt đầu bằng
    "PNG" vẫn lừa được ffprobe báo có stream video, trong khi giải mã thật
    sẽ hỏng — và nếu đem đi render với -loop, ffmpeg lặp vô hạn không ra
    khung nào. Giải mã thử là cổng chặn đúng."""
    try:
        cmd = [ffmpeg_bin(), "-v", "error", "-i", path,
               "-t", "0.5", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25,
                           **no_window_kwargs())
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _run(cmd, progress_cb=None, duration=None, label="", cwd=None, timeout=None):
    """Chạy lệnh, nếu có progress_cb thì parse -progress của ffmpeg.
    timeout (giây): đồng hồ canh — quá hạn thì diệt ffmpeg và báo lỗi rõ ràng,
    tránh treo vô hạn khi gặp input hỏng (vd ảnh nền lỗi khiến ffmpeg lặp
    mãi mà không ra khung hình nào)."""
    import threading

    if progress_cb and duration:
        cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, cwd=cwd,
                                **no_window_kwargs())
        killed = []

        def _kill():
            killed.append(True)
            proc.kill()

        timer = threading.Timer(timeout, _kill) if timeout else None
        if timer:
            timer.start()
        last = 0.0
        tail = []
        for line in proc.stdout:
            tail.append(line.rstrip())
            if len(tail) > 40:
                tail.pop(0)
            m = re.match(r"out_time_ms=(\d+)", line.strip())
            if m:
                t = int(m.group(1)) / 1_000_000.0
                pct = max(0.0, min(99.0, t / duration * 100.0))
                if pct - last >= 1.0:
                    last = pct
                    progress_cb(pct, label)
        proc.wait()
        if timer:
            timer.cancel()
        if killed:
            raise RuntimeError(
                f"ffmpeg quá thời gian ({timeout}s) ở bước {label} — "
                "file đầu vào có thể bị hỏng")
        if proc.returncode != 0:
            detail = "\n".join(tail[-6:])[-500:]
            raise RuntimeError(
                f"ffmpeg lỗi (mã {proc.returncode}) ở bước {label}: {detail}")
        progress_cb(100.0, label)
    else:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout or 3600, cwd=cwd,
                               **no_window_kwargs())
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"ffmpeg quá thời gian ({timeout}s) ở bước {label} — "
                "file đầu vào có thể bị hỏng")
        if r.returncode != 0:
            tail = (r.stderr or "")[-800:]
            raise RuntimeError(f"ffmpeg lỗi ở bước {label}: {tail}")


def extract_audio(src, dst_wav):
    """Trích audio về WAV stereo 44.1kHz s16 (định dạng làm việc chung)."""
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", src,
           "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", dst_wav]
    _run(cmd, label="trích âm thanh")


def decode_pcm16k(src_wav, dst_path):
    """Giải mã sẵn về PCM float32 16kHz mono (định dạng Whisper ăn trực
    tiếp) bằng ffmpeg của app — để worker Whisper nạp mảng số mà KHÔNG phải
    qua PyAV giải mã nữa (bớt một mắt xích native từng gây treo/lỗi khó
    lường trên máy Windows)."""
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", src_wav,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", dst_path]
    _run(cmd, label="giải mã PCM cho AI nghe lời")


def center_cut(in_wav, out_wav, progress_cb=None, duration=None):
    """Tách beat NHANH: lấy hiệu hai kênh (L-R) để triệt giọng hát ở giữa.
    Nhanh nhưng beat có thể mỏng và còn vọng giọng với bài mix hiện đại."""
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", in_wav,
           "-af", "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,"
                  "volume=2.0,alimiter=limit=0.95",
           "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out_wav]
    _run(cmd, progress_cb, duration, "tách beat nhanh")


GRADIENTS = {
    "demtim": ("Đêm tím", ["0x0d0518", "0x3d1470", "0x8b3fbf"]),
    "hoanghon": ("Hoàng hôn", ["0x1d0b38", "0xb7416b", "0xf7b733"]),
    "biensau": ("Biển sâu", ["0x02101f", "0x0a4d68", "0x088f8f"]),
    "rungdem": ("Rừng đêm", ["0x04140a", "0x14532d", "0x3f9d4e"]),
    "neon": ("Hồng neon", ["0x0f0219", "0x7b1e6e", "0xff2e88"]),
    "thanhpho": ("Đêm đô thị", ["0x050914", "0x1b2a6b", "0x3d5afe"]),
    "vangkim": ("Vàng kim", ["0x140b02", "0x6e4410", "0xd9a441"]),
    "hongdao": ("Hồng đào", ["0x1c0714", "0x83325c", "0xf78fb3"]),
    "xanhmint": ("Xanh mint", ["0x02120e", "0x0b5563", "0x2ec4b6"]),
    "domlua": ("Đốm lửa", ["0x120202", "0x7a1f0d", "0xf46036"]),
}


def _gradients_src(colors, w, h, animated=False):
    src = f"gradients=s={w}x{h}:" + ":".join(
        f"c{i}={c}" for i, c in enumerate(colors))
    src += f":nb_colors={len(colors)}"
    if not animated:
        src += f":x0=0:y0=0:x1={w}:y1={h}"
    return src


def make_gradient_bg(kind, out_png, size=(1920, 1080)):
    """Tạo ảnh nền gradient theo mẫu (3 điểm màu chuyển sắc rõ + vignette +
    nhiễu hạt nhẹ cho cảm giác cao cấp). kind lạ -> 'demtim'."""
    _label, colors = GRADIENTS.get(kind, GRADIENTS["demtim"])
    src = _gradients_src(colors, int(size[0]), int(size[1]))
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", src,
           "-vf", "vignette=angle=PI/5,noise=alls=5:allf=t",
           "-frames:v", "1", out_png]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       **no_window_kwargs())
    if r.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError("Không tạo được nền gradient: "
                           + (r.stderr or "")[-200:])
    return out_png


def make_gradient_video(kind, out_mp4, duration, size=(1280, 720)):
    """Tạo video nền gradient ĐỘNG (màu tự chuyển sắc chậm) dài tối đa 30
    giây để render lặp vòng — nền sống động thay vì một tấm ảnh tĩnh."""
    _label, colors = GRADIENTS.get(kind, GRADIENTS["demtim"])
    src = _gradients_src(colors, int(size[0]), int(size[1]), animated=True)
    dur = max(5.0, min(float(duration or 20), 30.0))
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", src,
           "-vf", "vignette=angle=PI/5",
           "-t", f"{dur:.1f}", "-r", "30", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                       **no_window_kwargs())
    if r.returncode != 0 or not os.path.exists(out_mp4):
        raise RuntimeError("Không tạo được nền động: "
                           + (r.stderr or "")[-200:])
    return out_mp4


def mix_with_guide(inst_wav, orig_wav, guide_pct, out_wav):
    """Trộn beat với một phần giọng gốc (guide_pct 0-40%) làm giọng dẫn."""
    g = max(0.0, min(40.0, float(guide_pct))) / 100.0
    if g <= 0.001:
        shutil.copyfile(inst_wav, out_wav)
        return
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", inst_wav, "-i", orig_wav,
           "-filter_complex",
           f"[0:a]volume=1.0[a0];[1:a]volume={g:.3f}[a1];"
           "[a0][a1]amix=inputs=2:duration=first:normalize=0,"
           "alimiter=limit=0.95[aout]",
           "-map", "[aout]", "-ac", "2", "-ar", "44100",
           "-c:a", "pcm_s16le", out_wav]
    _run(cmd, label="trộn giọng dẫn")


_NVENC_CACHE = {}


def has_nvenc():
    """True nếu máy mã hoá được bằng h264_nvenc THẬT (không chỉ liệt kê
    encoder — máy không có GPU NVIDIA vẫn có thể có tên encoder trong danh
    sách). Đo bằng cách mã hoá thử 15 khung; kết quả cache cho cả phiên."""
    if "ok" in _NVENC_CACHE:
        return _NVENC_CACHE["ok"]
    ok = False
    try:
        cmd = [ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i",
               "color=c=black:s=256x256:r=30", "-frames:v", "15",
               "-c:v", "h264_nvenc", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           **no_window_kwargs())
        ok = r.returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    _NVENC_CACHE["ok"] = ok
    return ok


def gpu_name():
    """Tên GPU NVIDIA (nvidia-smi) — chỉ để HIỂN THỊ nhãn, lỗi thì rỗng."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, **no_window_kwargs())
        names = (r.stdout or "").strip().splitlines()
        return names[0].strip() if names else ""
    except Exception:  # noqa: BLE001
        return ""


def _vcodec_args(enc, bitrate_k):
    """Tham số encoder video: 'nvenc' (GPU) hoặc 'cpu' (libx264).
    bitrate_k=None -> chế độ chất lượng (CRF/CQ như bản cũ)."""
    if enc == "nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p5"]
        if bitrate_k:
            args += ["-b:v", f"{int(bitrate_k)}k"]
        else:
            args += ["-rc", "vbr", "-cq", "20", "-b:v", "0"]
        return args
    args = ["-c:v", "libx264", "-preset", "medium"]
    if bitrate_k:
        bk = int(bitrate_k)
        args += ["-b:v", f"{bk}k", "-maxrate", f"{bk}k",
                 "-bufsize", f"{bk * 2}k"]
    else:
        args += ["-crf", "20"]
    return args


def render_video(bg, audio_wav, ass_path, out_mp4, duration, progress_cb=None,
                 size=(1920, 1080), progress_bar=False, encoder="cpu",
                 bitrate_k=None, bg_blur=0):
    """bg: {'type': 'color'|'image'|'video', 'value': hex hoặc đường dẫn}.
    Đốt chữ ASS karaoke lên nền theo size (mặc định 1920x1080; có thể là
    dọc 1080x1920 / vuông 1080x1080 / 4K 3840x2160), nhạc là audio_wav.
    progress_bar: vẽ thanh tiến trình mảnh ở mép trên video (kiểu Youka).
    ass_path=None -> KHÔNG đốt chữ (xuất video nền + nhạc trơn).
    encoder: 'cpu' (libx264) | 'nvenc' (GPU NVIDIA; sập thì tự lùi về CPU).
    bitrate_k: giới hạn bitrate video (kbps) — None = chất lượng CRF/CQ.
    bg_blur: 0-100, làm mờ nền ảnh/video (gblur).
    Trả về encoder THẬT đã dùng: 'nvenc' hoặc 'cpu'."""
    ff = ffmpeg_bin()
    w, h = int(size[0]), int(size[1])
    if bg.get("type") in ("image", "video") and not check_readable(bg.get("value") or ""):
        raise RuntimeError("File nền không đọc được — hãy chọn file khác")
    blur = ""
    if bg_blur and bg.get("type") in ("image", "video"):
        sigma = max(1.0, min(50.0, float(bg_blur) / 2.0))
        blur = f"gblur=sigma={sigma:.1f},"
    cmd = [ff, "-y", "-v", "error"]
    if bg.get("type") == "image":
        cmd += ["-loop", "1", "-framerate", "30", "-i", bg["value"]]
        vfilter = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},{blur}setsar=1[bg];")
    elif bg.get("type") == "video":
        cmd += ["-stream_loop", "-1", "-i", bg["value"]]
        vfilter = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},fps=30,{blur}setsar=1[bg];")
    else:
        color = (bg.get("value") or "#0b0e1a").replace("#", "0x")
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r=30"]
        vfilter = "[0:v]setsar=1[bg];"
    # Đường dẫn ASS KHÔNG nhúng thẳng vào filter (ký tự lạ như ':' của ổ đĩa
    # Windows, dấu cách, nháy đơn sẽ phá cú pháp filter của ffmpeg). Chạy
    # ffmpeg với cwd = thư mục chứa file ASS và chỉ dùng tên file trần.
    # Mọi đường dẫn khác chốt về tuyệt đối trước để không lệ thuộc cwd.
    audio_wav = os.path.abspath(audio_wav)
    out_mp4 = os.path.abspath(out_mp4)
    if bg.get("type") in ("image", "video"):
        bg = {**bg, "value": os.path.abspath(bg["value"])}
    ass_name = os.path.basename(ass_path) if ass_path else None
    ass_dir = os.path.dirname(os.path.abspath(ass_path)) if ass_path else None
    sub = f"[bg]ass='{ass_name}'[vsub];" if ass_path else "[bg]null[vsub];"
    bar_input = []
    if progress_bar and duration > 0:
        # Thanh tiến trình: dải vàng full bề ngang được phủ bằng overlay
        # với x trượt theo thời gian (ẩn dần ngoài mép trái -> hiện dần).
        # KHÔNG dùng drawbox/crop: cả hai đều không có biến t theo khung
        # cho tham số kích thước (đã đo thực tế trên bản ffmpeg này);
        # overlay thì có.
        vfilter += (sub +
                    f"[vsub][2:v]overlay=x='(t/{duration:.3f}-1)*overlay_w':y=0[vout]")
        bar_input = ["-f", "lavfi", "-i", f"color=c=0xFFD400:s={w}x6:r=30"]
    else:
        vfilter += sub.rstrip(";").replace("[vsub]", "[vout]")
    cmd += ["-i", audio_wav] + bar_input + [
            "-filter_complex", vfilter,
            "-map", "[vout]", "-map", "1:a"]
    tail = ["-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration:.3f}", "-movflags", "+faststart", out_mp4]
    big = 2 if w * h > 1920 * 1080 else 1
    timeout = int(max(180, duration * 6 * big))
    used = "nvenc" if encoder == "nvenc" else "cpu"
    try:
        _run(cmd + _vcodec_args(used, bitrate_k) + tail, progress_cb,
             duration, "xuất video", cwd=ass_dir, timeout=timeout)
    except RuntimeError:
        if used != "nvenc":
            raise
        # GPU báo có nhưng mã hoá sập giữa chừng -> lùi về CPU, không chết.
        used = "cpu"
        _run(cmd + _vcodec_args(used, bitrate_k) + tail, progress_cb,
             duration, "xuất video (CPU dự phòng)", cwd=ass_dir,
             timeout=timeout)
    return used


def extract_frame(video, at_sec, out_png):
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{at_sec:.2f}", "-i", video,
           "-frames:v", "1", out_png]
    _run(cmd, label="trích khung hình")
