"""Xử lý media bằng FFmpeg: trích âm thanh, cắt giọng nhanh, trộn, xuất video."""
import json
import os
import re
import shutil
import subprocess
import sys


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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
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
                                text=True, bufsize=1, cwd=cwd)
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
                               timeout=timeout or 3600, cwd=cwd)
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


def center_cut(in_wav, out_wav, progress_cb=None, duration=None):
    """Tách beat NHANH: lấy hiệu hai kênh (L-R) để triệt giọng hát ở giữa.
    Nhanh nhưng beat có thể mỏng và còn vọng giọng với bài mix hiện đại."""
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", in_wav,
           "-af", "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c1-0.5*c0,"
                  "volume=2.0,alimiter=limit=0.95",
           "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out_wav]
    _run(cmd, progress_cb, duration, "tách beat nhanh")


GRADIENTS = {
    "demtim": ("Đêm tím", ["0x160a2e", "0x5b2a86"]),
    "hoanghon": ("Hoàng hôn", ["0x2e1a47", "0xb7416b", "0xf2a65a"]),
    "biensau": ("Biển sâu", ["0x081c2c", "0x14607e"]),
    "rungdem": ("Rừng đêm", ["0x0a1f14", "0x2e7d4f"]),
    "neon": ("Hồng neon", ["0x14061f", "0xa4136b"]),
}


def make_gradient_bg(kind, out_png):
    """Tạo ảnh nền gradient 1920x1080 theo mẫu (kèm vignette + nhiễu hạt nhẹ
    cho cảm giác cao cấp). kind lạ -> dùng 'demtim'."""
    _label, colors = GRADIENTS.get(kind, GRADIENTS["demtim"])
    src = "gradients=s=1920x1080:" + ":".join(
        f"c{i}={c}" for i, c in enumerate(colors))
    src += f":nb_colors={len(colors)}:x0=0:y0=0:x1=1920:y1=1080"
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", src,
           "-vf", "vignette=angle=PI/5,noise=alls=5:allf=t",
           "-frames:v", "1", out_png]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(out_png):
        raise RuntimeError("Không tạo được nền gradient: "
                           + (r.stderr or "")[-200:])
    return out_png


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


def render_video(bg, audio_wav, ass_path, out_mp4, duration, progress_cb=None):
    """bg: {'type': 'color'|'image'|'video', 'value': hex hoặc đường dẫn}.
    Đốt chữ ASS karaoke lên nền 1920x1080, nhạc là audio_wav."""
    ff = ffmpeg_bin()
    if bg.get("type") in ("image", "video") and not check_readable(bg.get("value") or ""):
        raise RuntimeError("File nền không đọc được — hãy chọn file khác")
    cmd = [ff, "-y", "-v", "error"]
    if bg.get("type") == "image":
        cmd += ["-loop", "1", "-framerate", "30", "-i", bg["value"]]
        vfilter = ("[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                   "crop=1920:1080,setsar=1[bg];")
    elif bg.get("type") == "video":
        cmd += ["-stream_loop", "-1", "-i", bg["value"]]
        vfilter = ("[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                   "crop=1920:1080,fps=30,setsar=1[bg];")
    else:
        color = (bg.get("value") or "#0b0e1a").replace("#", "0x")
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s=1920x1080:r=30"]
        vfilter = "[0:v]setsar=1[bg];"
    # Đường dẫn ASS KHÔNG nhúng thẳng vào filter (ký tự lạ như ':' của ổ đĩa
    # Windows, dấu cách, nháy đơn sẽ phá cú pháp filter của ffmpeg). Chạy
    # ffmpeg với cwd = thư mục chứa file ASS và chỉ dùng tên file trần.
    # Mọi đường dẫn khác chốt về tuyệt đối trước để không lệ thuộc cwd.
    audio_wav = os.path.abspath(audio_wav)
    out_mp4 = os.path.abspath(out_mp4)
    if bg.get("type") in ("image", "video"):
        bg = {**bg, "value": os.path.abspath(bg["value"])}
    ass_name = os.path.basename(ass_path)
    ass_dir = os.path.dirname(os.path.abspath(ass_path))
    vfilter += f"[bg]ass='{ass_name}'[vout]"
    cmd += ["-i", audio_wav,
            "-filter_complex", vfilter,
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration:.3f}", "-movflags", "+faststart", out_mp4]
    _run(cmd, progress_cb, duration, "xuất video", cwd=ass_dir,
         timeout=int(max(180, duration * 6)))


def extract_frame(video, at_sec, out_png):
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{at_sec:.2f}", "-i", video,
           "-frames:v", "1", out_png]
    _run(cmd, label="trích khung hình")
