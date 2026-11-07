"""Tải nhạc/video từ YouTube bằng yt-dlp (chạy ngay trong app).

Mặc định chỉ tải LUỒNG ÂM THANH tốt nhất (vài MB) cho nhanh — làm karaoke
chỉ cần tiếng. Nếu người dùng chọn, tải thêm bản video (<=720p, ghép sẵn)
để dùng làm nền. Link lạ / không phải YouTube bị chặn ngay từ cửa với
thông báo rõ ràng.
"""
import os
import re

_ID = re.compile(r"(?:youtube\.com/(?:watch\?[^#]*v=|shorts/|live/|embed/|v/)|"
                 r"youtu\.be/|music\.youtube\.com/watch\?[^#]*v=)"
                 r"([A-Za-z0-9_-]{11})")
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url):
    """Trích mã video 11 ký tự từ mọi dạng link YouTube phổ biến.
    Không phải link YouTube / không có mã -> None."""
    url = str(url or "").strip()
    if _BARE_ID.match(url):
        return url
    m = _ID.search(url)
    return m.group(1) if m else None


def canonical_url(url):
    vid = parse_video_id(url)
    if not vid:
        raise ValueError(
            "Link không hợp lệ — hãy dán link video YouTube "
            "(dạng youtube.com/watch?v=... hoặc youtu.be/...)")
    return f"https://www.youtube.com/watch?v={vid}"


def download(url, work_dir, progress_cb=None, want_video=False,
             ffmpeg_dir=None):
    """Tải về thư mục work_dir. Trả về (src_path, title, video_path|None):
    - want_video=False: src_path là file ÂM THANH, video_path=None.
    - want_video=True: src_path là file VIDEO đã ghép (mp4), video_path
      chính là nó (dùng làm nguồn trích tiếng + nền video)."""
    cb = progress_cb or (lambda pct, label="": None)
    url = canonical_url(url)
    try:
        import yt_dlp
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Bản app này thiếu thư viện tải YouTube (yt-dlp): " + str(e)) from e
    for old in os.listdir(work_dir):
        if old.startswith("yt_src."):
            try:
                os.remove(os.path.join(work_dir, old))
            except OSError:
                pass

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            pct = (got * 100.0 / total) if total else 0.0
            cb(min(97.0, pct), "Đang tải từ YouTube...")
        elif d.get("status") == "finished":
            cb(98, "Tải xong, đang xử lý file...")

    opts = {
        "outtmpl": os.path.join(work_dir, "yt_src.%(ext)s"),
        "progress_hooks": [hook],
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "retries": 3, "socket_timeout": 30,
    }
    if want_video:
        opts["format"] = ("bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                          "best[height<=720][ext=mp4]/best[height<=720]/best")
        opts["merge_output_format"] = "mp4"
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
    cb(2, "Đang kết nối YouTube...")
    info = path = None
    last_err = None
    # Lượt 1 tải thường; bị YouTube chặn kiểu "xác nhận không phải robot" thì
    # thử lại bằng cookie của chính trình duyệt trên máy người dùng (Chrome
    # rồi Edge) — máy cá nhân thường qua được, máy chủ lạ thì không.
    variants = [opts]
    for browser in ("chrome", "edge"):
        o = dict(opts)
        o["cookiesfrombrowser"] = (browser, None, None, None)
        variants.append(o)
    for i, o in enumerate(variants):
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
                if want_video and not path.endswith(".mp4"):
                    alt = os.path.splitext(path)[0] + ".mp4"
                    if os.path.exists(alt):
                        path = alt
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            low = str(e).lower()
            blocked = ("sign in" in low or "not a bot" in low
                       or "login" in low or "cookies" in low)
            if not blocked or i == len(variants) - 1:
                break
            cb(4, "YouTube đòi xác nhận — thử lại bằng phiên đăng nhập "
                  "trình duyệt trên máy này...")
    if last_err is not None:
        e, msg = last_err, str(last_err)
        low = msg.lower()
        if "unavailable" in low or "private" in low or "removed" in low:
            raise ValueError(
                "Video không tải được (đã xoá, riêng tư hoặc bị chặn).") from e
        if "not a bot" in low:
            raise ValueError(
                "YouTube đang chặn tải từ mạng/IP này (chống robot). Hãy mở "
                "Chrome, đăng nhập YouTube sẵn rồi bấm chạy lại; nếu vẫn bị, "
                "đổi mạng khác sẽ tải được.") from e
        if "sign in" in low or "age" in low or "login" in low:
            raise ValueError(
                "Video yêu cầu đăng nhập / giới hạn tuổi — app không tải "
                "được loại này, thử video khác.") from e
        if "timed out" in low or "urlopen" in low or "network" in low \
                or "temporary failure" in low:
            raise ValueError(
                "Mạng chập chờn khi tải từ YouTube — thử lại sau ít phút.") from e
        raise RuntimeError("Tải YouTube lỗi: " + msg[-300:]) from e
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("Tải xong nhưng không thấy file — thử lại.")
    title = (info.get("title") or "Karaoke").strip()
    cb(100, "Đã tải xong")
    return path, title, (path if want_video else None)
