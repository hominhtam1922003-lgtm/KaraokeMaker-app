"""Lời bài hát: parse LRC, chia từ, sinh file ASS karaoke với thẻ \\k."""
import re

_LRC_TAG = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"\[(ar|ti|al|by|offset|re|ve):", re.IGNORECASE)
_OFFSET_TAG = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)


def parse_lrc(text):
    """Trả về list [{'start': float giây, 'text': str}] đã sắp theo thời gian.
    Áp dụng thẻ [offset:±ms] nếu có (dịch toàn bộ mốc giờ, không âm)."""
    mo = _OFFSET_TAG.search(text)
    shift = int(mo.group(1)) / 1000.0 if mo else 0.0
    out = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or _META_TAG.match(line):
            continue
        tags = list(_LRC_TAG.finditer(line))
        if not tags:
            continue
        lyric = _LRC_TAG.sub("", line).strip()
        if not lyric:
            continue
        for m in tags:
            mm, ss = int(m.group(1)), int(m.group(2))
            frac = m.group(3) or "0"
            frac = float("0." + frac) if len(frac) <= 3 else 0.0
            start = max(0.0, mm * 60 + ss + frac + shift)
            out.append({"start": start, "text": lyric})
    out.sort(key=lambda x: x["start"])
    return out


def parse_plain(text):
    """Lời dán tay: mỗi dòng một câu, bỏ dòng trống."""
    return [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]


def split_words(line):
    """Tách câu thành token theo khoảng trắng (tiếng Việt: mỗi token ~ 1 âm tiết)."""
    return [w for w in re.split(r"\s+", line.strip()) if w]


def _word_weight(word):
    # Trọng số theo số ký tự chữ/số, tối thiểu 1 — từ dài hát lâu hơn.
    n = len(re.sub(r"[^\w]", "", word, flags=re.UNICODE))
    return max(1, n)


def _ass_time(sec):
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_color(hex_rgb, fallback="#FFD400"):
    """#RRGGBB -> &HBBGGRR (màu ASS). Màu rác -> dùng fallback."""
    h = str(hex_rgb or "").lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h or ""):
        h = fallback.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _safe_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def build_ass(timed_lines, opts=None):
    """timed_lines: [{'start','end','text'}]. opts: color, sung_color, size, font,
    margin_v, max_chars (tự ngắt câu dài thành 2 sự kiện liên tiếp nếu vượt)."""
    opts = opts or {}
    sung = _ass_color(opts.get("color", "#FFD400"))       # màu sau khi hát qua (highlight)
    base = _ass_color(opts.get("base_color", "#FFFFFF"),
                      fallback="#FFFFFF")                 # màu chữ chưa hát tới
    outline = _ass_color(opts.get("outline_color", "#000000"), fallback="#000000")
    size = _safe_int(opts.get("size", 64), 64, 10, 200)
    font = str(opts.get("font", "Arial"))
    if not re.fullmatch(r"[\w\s\-]{1,40}", font):
        font = "Arial"
    margin_v = _safe_int(opts.get("margin_v", 70), 70, 0, 400)
    play_x, play_y = 1920, 1080

    header = (
        "[Script Info]\n"
        "Title: Karaoke\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_x}\n"
        f"PlayResY: {play_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Kara,{font},{size},{sung},{base},{outline},&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events = []
    for ln in timed_lines:
        start, end, text = float(ln["start"]), float(ln["end"]), ln["text"].strip()
        if end <= start:
            end = start + 0.5
        words = split_words(text)
        if not words:
            continue
        total_cs = int(round((end - start) * 100))
        weights = [_word_weight(w) for w in words]
        wsum = sum(weights) or 1
        parts = []
        used = 0
        for i, w in enumerate(words):
            if i == len(words) - 1:
                dur = max(1, total_cs - used)
            else:
                dur = max(1, int(round(total_cs * weights[i] / wsum)))
                used += dur
            safe = (w.replace("\\", "/")
                     .replace("{", "(").replace("}", ")"))
            parts.append(f"{{\\k{dur}}}{safe}")
        body = " ".join(parts)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Kara,,0,0,0,,{body}"
        )
    return header + "\n".join(events) + "\n"


def assign_ends(lines, song_duration, last_extra=4.0):
    """lines: [{'start','text'}] -> thêm 'end' = start của câu sau; câu cuối
    kết thúc ở min(start + last_extra*2, hết bài) nhưng tối thiểu start+1.5.
    Tự sắp xếp theo giờ bắt đầu và kẹp giờ âm về 0 — lời nạp vào lộn xộn
    thứ tự vẫn cho cửa sổ hiển thị hợp lệ."""
    norm = sorted(
        ({"start": max(0.0, float(ln["start"])), "text": ln["text"]} for ln in lines),
        key=lambda x: x["start"])
    out = []
    for i, ln in enumerate(norm):
        start = ln["start"]
        if i + 1 < len(norm):
            end = norm[i + 1]["start"]
        else:
            end = min(song_duration, start + max(3.0, last_extra))
            end = max(end, start + 1.5)
        end = max(end, start + 0.05)
        out.append({"start": start, "end": end, "text": ln["text"]})
    return out
