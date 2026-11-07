"""Tự căn nhịp bằng AI: Whisper nghe bài hát, đối chiếu với lời người dùng.

Whisper (faster-whisper, chạy CPU trên máy người dùng) chép lại bài hát kèm
mốc giờ từng từ. Module này đối chiếu bản chép đó với lời người dùng dán vào
(lời đúng chính tả) bằng thuật toán khớp chuỗi, suy ra giờ bắt đầu từng câu.
Câu không khớp trực tiếp được nội suy từ hai câu kề — người dùng vẫn sửa lại
bằng nút nudge như căn tay. Model tải về máy ở lần dùng đầu tiên và dùng lại
mãi về sau (thư mục models cạnh dữ liệu app).
"""
import os
import re
import unicodedata
from difflib import SequenceMatcher

MODEL_NAME = "small"


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


def align_lines(heard, line_texts, duration=0.0):
    """heard: [{'w','start','end'}] theo thứ tự thời gian.
    Trả về (starts, matched_ratio): starts[i] = giờ bắt đầu câu i (đã nội suy
    nếu câu không khớp trực tiếp); matched_ratio = tỉ lệ số từ trong lời người
    dùng khớp được với bản AI nghe (0..1)."""
    line_words = [_line_words(t) for t in line_texts]
    lyric_norm, owner = [], []
    for li, ws in enumerate(line_words):
        for w in ws:
            lyric_norm.append(w)
            owner.append(li)
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

    starts = [None] * len(line_texts)
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
    return out, round(ratio, 3)


def transcribe_words(wav_path, duration=0.0, progress_cb=None, models_dir=None):
    """Chép lời bài hát bằng Whisper. Trả về [{'w','start','end'}].
    Lần đầu sẽ tải model (~470 MB) vào models_dir rồi dùng lại."""
    cb = progress_cb or (lambda pct, label="": None)
    if models_dir:
        os.environ.setdefault("HF_HOME", models_dir)
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Bản app này thiếu thư viện AI nghe lời (faster-whisper): "
            + str(e)) from e
    cb(3, "Đang nạp model AI nghe lời — lần đầu dùng sẽ tải khoảng 470 MB, "
          "các lần sau dùng lại luôn")
    try:
        model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                             download_root=models_dir or None)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Không tải/nạp được model AI nghe lời (lần đầu cần có mạng): "
            + str(e)) from e
    cb(10, "Đang nghe bài hát...")
    words = []
    try:
        segments, _info = model.transcribe(
            wav_path, word_timestamps=True, beam_size=1, vad_filter=False)
        for seg in segments:
            for wd in (seg.words or []):
                words.append({"w": wd.word, "start": float(wd.start),
                              "end": float(wd.end)})
            if duration:
                cb(min(96.0, 10 + 86 * float(seg.end) / duration),
                   "Đang nghe & chép lời bài hát...")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("AI nghe bài hát bị lỗi: " + str(e)) from e
    if not words:
        raise ValueError(
            "AI không nghe rõ lời nào trong bài này — thử căn tay bằng Space")
    cb(98, "Đang đối chiếu với lời đã dán...")
    return words
