"""Tự căn nhịp bằng AI: Whisper nghe bài hát, đối chiếu với lời người dùng.

Whisper (faster-whisper, chạy CPU trên máy người dùng) chép lại bài hát kèm
mốc giờ từng từ. Module này đối chiếu bản chép đó với lời người dùng dán vào
(lời đúng chính tả) bằng thuật toán khớp chuỗi, suy ra giờ bắt đầu từng câu
và giờ hát thật của từng từ. Câu không khớp trực tiếp được nội suy từ hai
câu kề — người dùng vẫn sửa lại bằng nút nudge như căn tay.

Chế độ TỰ ĐỘNG TOÀN PHẦN: nếu người dùng không dán lời, chính bản chép của
Whisper được cắt thành câu (theo đoạn + dấu câu) và dùng làm lời luôn — mốc
giờ từng từ là giờ thật, khỏi cần đối chiếu.

Model tải về máy ở lần dùng đầu tiên và dùng lại mãi về sau (thư mục models
cạnh dữ liệu app).
"""
import os
import re
import unicodedata
from difflib import SequenceMatcher

MODEL_NAME = "small"

_PUNCT_END = (",", ".", "?", "!", "…", ":", ";")
_MAX_WORDS_PER_LINE = 12


def strip_diacritics(s):
    s = str(s).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_word(w, strip=False):
    """Chuẩn hoá một từ để đối chiếu: thường hoá, bỏ dấu câu; strip=True thì
    bỏ luôn dấu tiếng Việt (lời dán thiếu dấu vẫn khớp được bản nghe)."""
    w = unicodedata.normalize("NFC", str(w)).lower()
    w = re.sub(r"[^\w]", "", w, flags=re.UNICODE)
    if strip:
        w = strip_diacritics(w)
    return w


def _line_words(text):
    return [w for w in (norm_word(t) for t in str(text).split()) if w]


def _match_positions(heard_norm, lyric_norm):
    """Khớp hai dãy từ đã chuẩn hoá. Trả về {chỉ số từ phía lời: chỉ số từ
    phía nghe} theo các khối bằng nhau của SequenceMatcher."""
    pairs = [(i, h) for i, h in enumerate(heard_norm) if h]
    sm = SequenceMatcher(a=[p[1] for p in pairs], b=lyric_norm, autojunk=False)
    mapping = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[j1 + k] = pairs[i1 + k][0]
    return mapping


def _compute_mapping(heard, line_texts):
    """Đối chiếu lời với bản nghe. Trả về (mapping, ratio, line_words).
    Tự thử lượt bỏ dấu nếu lượt giữ dấu khớp kém."""
    line_words = [_line_words(t) for t in line_texts]
    lyric_norm = []
    for ws in line_words:
        lyric_norm.extend(ws)
    if not lyric_norm:
        raise ValueError("Lời chưa có chữ nào để căn")
    if not heard:
        raise ValueError("AI không nghe được lời nào trong bài này")

    def run(strip):
        heard_norm = [norm_word(h["w"], strip) for h in heard]
        lyr = [strip_diacritics(w) if strip else w for w in lyric_norm]
        return _match_positions(heard_norm, lyr)

    mapping = run(False)
    ratio = len(mapping) / len(lyric_norm)
    if ratio < 0.5:  # lời dán thiếu dấu / lệch nhiều: thử lượt bỏ dấu
        m2 = run(True)
        if len(m2) > len(mapping):
            mapping, ratio = m2, len(m2) / len(lyric_norm)
    return mapping, ratio, line_words


def _starts_from_mapping(heard, line_words, mapping, duration=0.0):
    """Giờ bắt đầu từng câu từ mapping; câu không khớp thì nội suy."""
    starts = [None] * len(line_words)
    pos = 0
    for li, ws in enumerate(line_words):
        idxs = [mapping[p] for p in range(pos, pos + len(ws)) if p in mapping]
        if idxs:
            starts[li] = float(heard[min(idxs)]["start"])
        pos += len(ws)
    known = [i for i, s in enumerate(starts) if s is not None]
    if not known:
        raise ValueError(
            "AI nghe được lời nhưng không khớp với lời đã dán — kiểm tra lại "
            "lời có đúng bài / đúng ngôn ngữ không")
    for i in range(len(starts)):
        if starts[i] is not None:
            continue
        prev = max((k for k in known if k < i), default=None)
        nxt = min((k for k in known if k > i), default=None)
        if prev is not None and nxt is not None:
            frac = (i - prev) / (nxt - prev)
            starts[i] = starts[prev] + frac * (starts[nxt] - starts[prev])
        elif nxt is not None:
            starts[i] = max(0.0, starts[nxt] - 2.2 * (nxt - i))
        else:
            starts[i] = starts[prev] + 2.5 * (i - prev)
    out, last = [], 0.0
    for s in starts:
        s = max(float(s), 0.0)
        if out:
            s = max(s, last + 0.1)
        if duration:
            s = min(s, max(0.0, duration - 0.3))
        out.append(round(s, 2))
        last = s
    return out


def align_lines(heard, line_texts, duration=0.0):
    """Trả về (starts, matched_ratio) — xem align_full để lấy thêm giờ từng từ."""
    mapping, ratio, line_words = _compute_mapping(heard, line_texts)
    starts = _starts_from_mapping(heard, line_words, mapping, duration)
    return starts, round(ratio, 3)


def align_full(heard, line_texts, duration=0.0):
    """Như align_lines nhưng kèm giờ hát thật của từng từ:
    {'starts': [...], 'ratio': float,
     'words': [[(start, end), ...] theo từng câu]}.
    Từ không khớp trực tiếp được nội suy tuyến tính giữa hai từ khớp kề bên
    trên trục chỉ số từ — đủ mượt cho hiệu ứng chữ chạy."""
    mapping, ratio, line_words = _compute_mapping(heard, line_texts)
    starts = _starts_from_mapping(heard, line_words, mapping, duration)
    total = sum(len(ws) for ws in line_words)
    known_idx = sorted(mapping.keys())

    def word_time(p):
        """(start, end) của từ lời thứ p: khớp trực tiếp hoặc nội suy."""
        if p in mapping:
            h = heard[mapping[p]]
            return float(h["start"]), float(h["end"])
        prev = max((k for k in known_idx if k < p), default=None)
        nxt = min((k for k in known_idx if k > p), default=None)
        if prev is not None and nxt is not None:
            hp, hn = heard[mapping[prev]], heard[mapping[nxt]]
            frac = (p - prev) / (nxt - prev)
            s = float(hp["end"]) + frac * (float(hn["start"]) - float(hp["end"]))
            return s, s + 0.25
        if nxt is not None:
            s = max(0.0, float(heard[mapping[nxt]]["start"]) - 0.3 * (nxt - p))
            return s, s + 0.25
        s = float(heard[mapping[prev]]["end"]) + 0.3 * (p - prev)
        return s, s + 0.25

    words_out, pos = [], 0
    for li, ws in enumerate(line_words):
        row = []
        for k in range(len(ws)):
            s, e = word_time(pos + k)
            s = max(s, starts[li])
            if row:
                s = max(s, row[-1][1] - 0.05)
            e = max(e, s + 0.05)
            row.append((round(s, 2), round(e, 2)))
        words_out.append(row)
        pos += len(ws)
    return {"starts": starts, "ratio": round(ratio, 3), "words": words_out}


# ---------------- Whisper ----------------

def _load_model(models_dir):
    if models_dir:
        os.environ.setdefault("HF_HOME", models_dir)
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Bản app này thiếu thư viện AI nghe lời (faster-whisper): "
            + str(e)) from e
    try:
        return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                            download_root=models_dir or None)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Không tải/nạp được model AI nghe lời (lần đầu cần có mạng): "
            + str(e)) from e


def transcribe_segments(wav_path, duration=0.0, progress_cb=None,
                        models_dir=None):
    """Chép lời bài hát bằng Whisper. Trả về các đoạn:
    [{'text','start','end','words':[{'w','start','end'}]}]."""
    cb = progress_cb or (lambda pct, label="": None)
    cb(3, "Đang nạp model AI nghe lời — lần đầu dùng sẽ tải khoảng 470 MB, "
          "các lần sau dùng lại luôn")
    model = _load_model(models_dir)
    cb(10, "Đang nghe bài hát...")
    segments = []
    try:
        segs, _info = model.transcribe(
            wav_path, word_timestamps=True, beam_size=1, vad_filter=False)
        for seg in segs:
            words = [{"w": (wd.word or "").strip(),
                      "start": float(wd.start), "end": float(wd.end)}
                     for wd in (seg.words or []) if (wd.word or "").strip()]
            segments.append({"text": (seg.text or "").strip(),
                             "start": float(seg.start),
                             "end": float(seg.end), "words": words})
            if duration:
                cb(min(96.0, 10 + 86 * float(seg.end) / duration),
                   "Đang nghe & chép lời bài hát...")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("AI nghe bài hát bị lỗi: " + str(e)) from e
    if not segments:
        raise ValueError(
            "AI không nghe rõ lời nào trong bài này — thử căn tay bằng Space")
    cb(98, "Đang xử lý lời...")
    return segments


def transcribe_words(wav_path, duration=0.0, progress_cb=None, models_dir=None):
    """Bản phẳng của transcribe_segments: [{'w','start','end'}]."""
    segs = transcribe_segments(wav_path, duration, progress_cb, models_dir)
    return [w for seg in segs for w in seg["words"]]


def segments_to_lines(segments):
    """Cắt các đoạn Whisper thành câu karaoke: mỗi đoạn là một câu; đoạn dài
    hơn _MAX_WORDS_PER_LINE từ thì ngắt ở dấu câu gần nhất. Bỏ các đoạn ghi
    chú kiểu [âm nhạc]. Kèm giờ thật từng từ cho hiệu ứng chữ chạy mượt."""
    lines = []
    for seg in segments:
        words = seg["words"]
        text = seg["text"].strip()
        if not words or not text:
            continue
        if (text.startswith("[") and text.endswith("]")) or \
                (text.startswith("(") and text.endswith(")")):
            continue  # [âm nhạc], (tiếng vỗ tay)... không phải lời hát
        chunks, cur = [], []
        for wd in words:
            cur.append(wd)
            ends_sentence = wd["w"].rstrip().endswith(_PUNCT_END)
            if len(cur) >= _MAX_WORDS_PER_LINE or \
                    (ends_sentence and len(cur) >= 6):
                chunks.append(cur)
                cur = []
        if cur:
            if chunks and len(cur) <= 3:  # đuôi quá ngắn: gộp vào câu trước
                chunks[-1].extend(cur)
            else:
                chunks.append(cur)
        for ch in chunks:
            txt = " ".join(w["w"] for w in ch).strip()
            txt = re.sub(r"\s+([,.?!…:;])", r"\1", txt)
            if not txt:
                continue
            lines.append({
                "text": txt,
                "start": round(float(ch[0]["start"]), 2),
                "end": round(float(ch[-1]["end"]), 2),
                "words": [(round(float(w["start"]), 2),
                           round(float(w["end"]), 2)) for w in ch],
            })
    lines.sort(key=lambda x: x["start"])
    return lines
