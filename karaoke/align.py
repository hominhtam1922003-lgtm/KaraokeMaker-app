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
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
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
    line_ok = []
    for li, ws in enumerate(line_words):
        row = []
        direct = False
        for k in range(len(ws)):
            if pos + k in mapping:
                direct = True
            s, e = word_time(pos + k)
            s = max(s, starts[li])
            if row:
                s = max(s, row[-1][1] - 0.05)
            e = max(e, s + 0.05)
            row.append((round(s, 2), round(e, 2)))
        words_out.append(row)
        # line_ok: câu có ÍT NHẤT một từ khớp trực tiếp với bản nghe. Câu
        # toàn nội suy = "chưa khớp" — Studio (v4) gắn cảnh báo để người
        # dùng soát lại/gắn nhịp tay câu đó thay vì tin mù.
        line_ok.append(direct)
        pos += len(ws)
    return {"starts": starts, "ratio": round(ratio, 3), "words": words_out,
            "line_ok": line_ok}


# ---------------- Whisper ----------------

def _load_model(models_dir, cpu_threads=0):
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
                            download_root=models_dir or None,
                            cpu_threads=int(cpu_threads or 0))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Không tải/nạp được model AI nghe lời (lần đầu cần có mạng): "
            + str(e)) from e


def load_model_only(models_dir, progress_cb=None):
    """Nạp model một lần chỉ để chắc chắn nó đã tải xong về máy (dùng khi
    nhiều tác vụ song song cần tránh tải trùng nhau). Chạy ở worker con —
    nạp model không bao giờ được phép kéo sập app chính."""
    if os.environ.get("KARAOKE_WHISPER_INPROCESS") == "1":
        _load_model(models_dir)
        return
    try:
        _run_worker(["load-only", str(models_dir or "")], progress_cb)
    except _WorkerSpawnError:
        _load_model(models_dir)


class _WorkerSpawnError(RuntimeError):
    """Không khởi động được tiến trình con — nơi gọi sẽ lùi về chạy trong
    tiến trình chính (thà chạy chung còn hơn không chạy được)."""


class _WorkerStall(RuntimeError):
    """Worker vẫn sống nhưng câm lặng quá lâu — coi như đã treo."""


def _env_seconds(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return float(default)


def _worker_cmd():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--whisper-worker"]
    return [sys.executable,
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "whisper_worker.py")]


def _run_worker(args, progress_cb):
    """Chạy worker Whisper ở tiến trình con, chuyển tiếp tiến độ, trả kết
    quả. Ba lớp bảo vệ:
    - Worker sập (kể cả segfault native) -> RuntimeError rõ ràng, app sống.
    - Worker CÂM LẶNG quá KARAOKE_WHISPER_STALL_S giây (mặc định 120) ->
      giết ngay, ném _WorkerStall để nơi gọi thử lại bằng cấu hình khác
      (sự cố thật 07/11/2026: treo 12 phút ở đúng một con số phần trăm).
    - Quá KARAOKE_WHISPER_HEARTBEAT_S giây (mặc định 20) không có tiến độ
      mới -> tự phát nhịp tim "Vẫn đang xử lý... (đã N giây)" để người dùng
      biết app còn sống, khỏi đoán mò."""
    cb = progress_cb or (lambda pct, label="": None)
    stall_s = _env_seconds("KARAOKE_WHISPER_STALL_S", 120)
    beat_s = _env_seconds("KARAOKE_WHISPER_HEARTBEAT_S", 20)
    try:
        from karaoke.media import no_window_kwargs
        nw = no_window_kwargs()
    except Exception:  # noqa: BLE001
        nw = {}
    try:
        proc = subprocess.Popen(
            _worker_cmd() + args, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", **nw)
    except Exception as e:  # noqa: BLE001
        raise _WorkerSpawnError(
            "Không khởi động được AI nghe lời: " + str(e)) from e
    err_tail = []

    def drain_err():
        try:
            for line in proc.stderr:
                err_tail.append(line.rstrip())
                del err_tail[:-20]
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=drain_err, daemon=True).start()
    lines = queue.Queue()

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        except Exception:  # noqa: BLE001
            pass
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    started = last_line = last_beat = time.time()
    last_pct = 0.0
    result, error = None, None
    while True:
        try:
            line = lines.get(timeout=2)
        except queue.Empty:
            now = time.time()
            if now - last_line > stall_s:
                proc.kill()
                raise _WorkerStall(
                    f"AI nghe lời không phản hồi suốt {stall_s:.0f} giây — "
                    "coi như đã treo")
            if now - last_line >= beat_s and now - last_beat >= beat_s:
                last_beat = now
                cb(last_pct, "Vẫn đang nghe & chép lời... (đã "
                             f"{int(now - started)} giây — bài dài/máy bận "
                             "sẽ lâu hơn)")
            continue
        if line is None:
            break
        last_line = time.time()
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "result" in msg:
            result = msg["result"]
        elif "error" in msg:
            error = msg["error"]
        elif "pct" in msg:
            last_pct = float(msg["pct"])
            cb(last_pct, msg.get("label", ""))
    proc.wait()
    if error:
        raise RuntimeError(error)
    if result is None:
        tail = "\n".join(err_tail[-5:])
        raise RuntimeError(
            "AI nghe lời bị sập giữa chừng (mã lỗi "
            f"{proc.returncode}) — app vẫn chạy bình thường, thử bấm lại. "
            "Chi tiết: " + (tail or "không có thêm thông tin"))
    return result


def _synth_words(segments):
    """Đoạn không có giờ từng từ (chế độ nghe dự phòng): chia đều khoảng hát
    của đoạn cho từng từ để chữ vẫn quét theo nhịp gần đúng thay vì đứng im."""
    for seg in segments:
        if seg.get("words"):
            continue
        words = (seg.get("text") or "").split()
        if not words:
            seg["words"] = []
            continue
        t0, t1 = float(seg["start"]), float(seg["end"])
        if t1 <= t0:
            t1 = t0 + 0.3 * len(words)
        step = (t1 - t0) / len(words)
        seg["words"] = [{"w": w, "start": t0 + i * step,
                         "end": t0 + (i + 1) * step}
                        for i, w in enumerate(words)]
    return segments


def transcribe_segments(wav_path, duration=0.0, progress_cb=None,
                        models_dir=None):
    """Chép lời bài hát bằng Whisper (ở TIẾN TRÌNH CON — xem whisper_worker).

    THANG DỰ PHÒNG 3 NẤC (treo nấc nào xuống nấc đó, mục tiêu là RA ĐƯỢC
    KẾT QUẢ thay vì đứng hình):
      1) giờ từng từ thật, luồng CPU = số nhân (tối đa 8);
      2) giờ từng từ thật, chỉ 2 luồng (CTranslate2 để mặc định luồng từng
         gây treo trên Windows);
      3) chỉ giờ theo ĐOẠN + tự chia giờ cho từng từ (nhanh & khó treo nhất).
    Âm thanh được giải mã sẵn thành PCM bằng ffmpeg của app (worker nạp
    mảng số thẳng cho Whisper, bỏ khâu giải mã PyAV trong worker).
    Trả về: [{'text','start','end','words':[{'w','start','end'}]}]."""
    cb = progress_cb or (lambda pct, label="": None)
    if os.environ.get("KARAOKE_WHISPER_INPROCESS") == "1":
        return _transcribe_inprocess(wav_path, duration, cb, models_dir)
    src_arg, pcm_flag = str(wav_path), "0"
    try:
        from karaoke import media as _media
        pcm_path = str(wav_path) + ".pcm16k"
        _media.decode_pcm16k(str(wav_path), pcm_path)
        src_arg, pcm_flag = pcm_path, "1"
    except Exception:  # noqa: BLE001
        pass  # giải mã sẵn không được -> worker tự đọc file như cũ
    cores = os.cpu_count() or 4
    base = ["segments", src_arg, str(models_dir or ""),
            str(float(duration or 0))]
    attempts = [
        base + [str(max(2, min(8, cores))), "1", pcm_flag],
        base + ["2", "1", pcm_flag],
        base + ["2", "0", pcm_flag],
    ]
    last_err = None
    for i, args in enumerate(attempts):
        try:
            segments = _run_worker(args, cb)
            if not segments:
                raise ValueError(
                    "AI không nghe rõ lời nào trong bài này — thử căn tay "
                    "bằng Space")
            if args[-2] == "0":
                _synth_words(segments)
            return segments
        except _WorkerSpawnError:
            return _transcribe_inprocess(wav_path, duration, cb, models_dir)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if i < len(attempts) - 1:
                cb(12, "AI nghe bị kẹt — đang tự thử lại bằng cách khác "
                       f"(lần {i + 2}/3)...")
    raise last_err


def _transcribe_inprocess(wav_path, duration=0.0, progress_cb=None,
                          models_dir=None):
    """Đường dự phòng: chép lời ngay trong tiến trình chính (chỉ khi không
    khởi động được worker con, hoặc khi biến KARAOKE_WHISPER_INPROCESS=1)."""
    cb = progress_cb or (lambda pct, label="": None)
    cb(3, "Đang nạp model AI nghe lời — lần đầu dùng sẽ tải khoảng 470 MB, "
          "các lần sau dùng lại luôn")
    model = _load_model(models_dir,
                        cpu_threads=max(2, min(8, os.cpu_count() or 4)))
    cb(10, "Đang nghe bài hát...")
    segments = []
    try:
        segs, _info = model.transcribe(
            wav_path, word_timestamps=True, beam_size=1, vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt="Sau đây là lời một bài hát tiếng Việt, được hát "
                           "rõ ràng và viết có dấu đầy đủ.")
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
        from karaoke import lyrics as _lyr
        if _lyr.is_junk_line(text):
            continue  # lời kêu gọi của kênh (subscribe...) — không phải lời hát
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
