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


_SECTION = re.compile(
    r"(lyrics?|verse|chorus|hook|bridge|intro|outro|pre[-\s]?chorus|"
    r"post[-\s]?chorus|refrain|điệp khúc|lời|phần|đoạn)\b", re.IGNORECASE)
_SEPARATOR = re.compile(r"^[-=*_~.·•\s]+$")
_BRACKETED = re.compile(r"^[\[(].{0,40}[\])]$")


def clean_line(line):
    """Một dòng lời dán vào -> câu hát sạch, hoặc None nếu là dòng rác:
    nhãn mục kiểu Musixmatch (--:--Verse 1:, --:--Lyrics:), [Chorus],
    (Hook), đường gạch trang trí, nhãn 'Verse 1:' đứng một mình."""
    s = (line or "").strip()
    if not s or _SEPARATOR.match(s):
        return None
    if _BRACKETED.match(s) and len(s.split()) <= 6:
        return None
    if s.endswith(":") and len(s) <= 30 and _SECTION.match(s):
        return None
    if s.startswith("--:--"):
        rest = s[len("--:--"):].strip()
        if not rest or _SECTION.match(rest) or (len(rest) <= 30
                                                and rest.endswith(":")):
            return None
        s = rest
    return s or None


def parse_plain(text):
    """Lời dán tay: mỗi dòng một câu, bỏ dòng trống và dòng rác (nhãn mục)."""
    out = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        s = clean_line(ln)
        if s:
            out.append(s)
    return out


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


def _word_start(wt):
    return float(wt["start"]) if isinstance(wt, dict) else float(wt[0])


def build_ass(timed_lines, opts=None):
    """timed_lines: [{'start','end','text', tuỳ chọn 'words': [(start,end)...]}].
    opts: color (màu đã hát), base_color (màu chưa hát), outline_color, size,
    font, margin_v, effect ('sweep' = quét mượt \\kf | 'pop' = nhảy từng từ \\k),
    fade (bool: mở/đóng câu bằng mờ dần), align (2 đáy | 8 đỉnh | 5 giữa),
    outline_w, two_line (hiện câu kế tiếp mờ ở dưới), title (thẻ tên bài mở đầu)."""
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
    align = _safe_int(opts.get("align", 2), 2, 1, 9)
    outline_w = _safe_int(opts.get("outline_w", 3), 3, 0, 8)
    tag = "kf" if str(opts.get("effect", "sweep")) != "pop" else "k"
    fade = bool(opts.get("fade", True))
    two_line = bool(opts.get("two_line", False))
    title = str(opts.get("title") or "").strip()
    play_x, play_y = 1920, 1080

    style_fmt = (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Kara,{font},{size},{sung},{base},{outline},&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline_w},1,{align},40,40,{margin_v},1\n"
    )
    if two_line:
        dim = "&H59" + base[4:]  # màu câu kế: mờ ~65%
        style_fmt += (
            f"Style: KaraNext,{font},{max(20, int(size * 0.72))},{dim},{dim},"
            f"{outline},&H64000000,-1,0,0,0,100,100,0,0,1,2,1,{align},40,40,16,1\n"
        )
    if title:
        style_fmt += (
            f"Style: KaraTitle,{font},{int(size * 1.25)},{sung},{base},"
            f"{outline},&H64000000,-1,0,0,0,100,100,0,0,1,3,2,5,40,40,0,1\n"
        )

    header = (
        "[Script Info]\n"
        "Title: Karaoke\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_x}\n"
        f"PlayResY: {play_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        + style_fmt + "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def safe_text(t):
        return (str(t).replace("\\", "/")
                .replace("{", "(").replace("}", ")"))

    norm = []
    for ln in timed_lines:
        start, end = float(ln["start"]), float(ln["end"])
        if end <= start:
            end = start + 0.5
        words = split_words(str(ln["text"]))
        if words:
            norm.append((start, end, str(ln["text"]).strip(), words,
                         ln.get("words")))

    events = []
    if title and norm:
        t_end = min(4.0, norm[0][0]) if norm[0][0] > 1.5 else 3.0
        events.append(
            f"Dialogue: 2,0:00:00.00,{_ass_time(t_end)},KaraTitle,,0,0,0,,"
            f"{{\\fad(300,400)}}{safe_text(title)}")
    for idx, (start, end, text, words, wtimes) in enumerate(norm):
        total_cs = max(len(words), int(round((end - start) * 100)))
        parts = []
        if wtimes and len(wtimes) == len(words):
            pts = []
            for wt in wtimes:
                p = max(start, min(end, _word_start(wt)))
                if pts:
                    p = max(p, pts[-1] + 0.01)
                pts.append(p)
            lead = int(round((pts[0] - start) * 100)) if pts[0] > start + 0.02 else 0
            lead = max(0, min(lead, total_cs - len(words)))
            if lead:
                parts.append(f"{{\\k{lead}}}")
            used = lead
            for i, w in enumerate(words):
                if i == len(words) - 1:
                    dur = max(1, total_cs - used)
                else:
                    dur = max(1, int(round((pts[i + 1] - pts[i]) * 100)))
                    used += dur
                parts.append(f"{{\\{tag}{dur}}}{safe_text(w)}")
        else:
            weights = [_word_weight(w) for w in words]
            wsum = sum(weights) or 1
            used = 0
            for i, w in enumerate(words):
                if i == len(words) - 1:
                    dur = max(1, total_cs - used)
                else:
                    dur = max(1, int(round(total_cs * weights[i] / wsum)))
                    used += dur
                parts.append(f"{{\\{tag}{dur}}}{safe_text(w)}")
        body = " ".join(parts)
        if fade:
            body = "{\\fad(120,180)}" + body
        events.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Kara,,0,0,0,,{body}")
        if two_line and idx + 1 < len(norm):
            ntext = safe_text(norm[idx + 1][2])
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},KaraNext,,0,0,0,,"
                f"{{\\fad(150,150)}}{ntext}")
    return header + "\n".join(events) + "\n"


def assign_ends(lines, song_duration, last_extra=4.0):
    """lines: [{'start','text', tuỳ chọn 'end','words'}] -> chốt 'end':
    ưu tiên 'end' có sẵn nếu hợp lệ (bản chép AI có giờ kết thúc thật), không
    thì lấy start của câu sau; câu cuối kết thúc ở min(start + last_extra*2,
    hết bài) nhưng tối thiểu start+1.5. Giữ nguyên 'words' (giờ từng từ) nếu có.
    Tự sắp xếp theo giờ bắt đầu và kẹp giờ âm về 0."""
    norm = sorted(
        ({"start": max(0.0, float(ln["start"])), "text": ln["text"],
          "end": ln.get("end"), "words": ln.get("words")} for ln in lines),
        key=lambda x: x["start"])
    out = []
    for i, ln in enumerate(norm):
        start = ln["start"]
        nxt = norm[i + 1]["start"] if i + 1 < len(norm) else song_duration
        given = ln.get("end")
        if isinstance(given, (int, float)) and not isinstance(given, bool) \
                and start + 0.05 < float(given):
            end = min(float(given), max(nxt, start + 0.05))
        elif i + 1 < len(norm):
            end = nxt
        else:
            end = min(song_duration, start + max(3.0, last_extra))
            end = max(end, start + 1.5)
        end = max(end, start + 0.05)
        item = {"start": start, "end": end, "text": ln["text"]}
        if ln.get("words"):
            item["words"] = ln["words"]
        out.append(item)
    return out
