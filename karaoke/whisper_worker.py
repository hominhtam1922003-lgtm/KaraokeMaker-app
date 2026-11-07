"""Worker Whisper chạy TIẾN TRÌNH RIÊNG — tách khỏi app chính.

Lý do: faster-whisper/ctranslate2 là thư viện native; nếu nó sập (segfault)
khi nạp model thì tiến trình app chính chết theo, giao diện đóng băng giữa
chừng mà không hiện lỗi gì (sự cố thật đã gặp ở bản 1.1.0: bấm Tự căn, thanh
tiến độ đứng ở 3% rồi im luôn). Chạy ở tiến trình con: con sập thì cha vẫn
sống, bắt được mã lỗi và báo rõ cho người dùng.

Giao thức: in từng dòng JSON ra stdout:
  {"pct": float, "label": str}  — tiến độ (kể cả % tải model lần đầu)
  {"result": ...}               — kết quả cuối cùng
  {"error": str}                — lỗi (thoát mã 1)

Chạy độc lập được (không import package karaoke):
  python whisper_worker.py segments <wav> <models_dir|""> <duration>
  python whisper_worker.py load-only <models_dir|"">
Trong bản đóng gói: KaraokeMaker.exe --whisper-worker <tham số như trên>.
"""
import json
import os
import sys
import threading
import time

MODEL_NAME = "small"
MODEL_BYTES = 470_000_000  # kích thước gần đúng của model small (để ước % tải)


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _load_model(models_dir, progress=True):
    if models_dir:
        os.environ.setdefault("HF_HOME", models_dir)
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Bản app này thiếu thư viện AI nghe lời (faster-whisper): "
            + str(e)) from e
    stop = threading.Event()

    def watch():
        # Trong lúc nạp/tải model: đo dung lượng thư mục model mỗi giây để
        # thanh tiến độ NHÚC NHÍCH thật (bản cũ đứng im ở 3% suốt phút tải).
        while not stop.is_set():
            size = _dir_size(models_dir) if models_dir else 0
            mb = size / 1e6
            pct = 3.0 + min(21.0, 21.0 * size / MODEL_BYTES)
            emit({"pct": round(pct, 1),
                  "label": "Đang tải/nạp model AI nghe lời — đã có "
                           f"{mb:.0f} MB (lần đầu ~470 MB, các lần sau "
                           "dùng lại luôn)"})
            time.sleep(1.0)

    watcher = None
    if progress and models_dir:
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
    try:
        return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                            download_root=models_dir or None)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Không tải/nạp được model AI nghe lời (lần đầu cần có mạng): "
            + str(e)) from e
    finally:
        stop.set()


def _segments(wav_path, models_dir, duration):
    emit({"pct": 3, "label": "Đang nạp model AI nghe lời — lần đầu dùng sẽ "
                            "tải khoảng 470 MB, các lần sau dùng lại luôn"})
    model = _load_model(models_dir)
    emit({"pct": 10, "label": "Đang nghe bài hát..."})
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
                emit({"pct": round(min(96.0, 10 + 86 * float(seg.end)
                                       / duration), 1),
                      "label": "Đang nghe & chép lời bài hát..."})
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("AI nghe bài hát bị lỗi: " + str(e)) from e
    if not segments:
        raise ValueError(
            "AI không nghe rõ lời nào trong bài này — thử căn tay bằng Space")
    emit({"pct": 98, "label": "Đang xử lý lời..."})
    return segments


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        mode = argv[0]
        if mode == "load-only":
            models_dir = argv[1] if len(argv) > 1 and argv[1] else None
            emit({"pct": 3, "label": "Đang nạp model AI nghe lời..."})
            _load_model(models_dir)
            emit({"result": True})
            return 0
        if mode == "segments":
            wav_path = argv[1]
            models_dir = argv[2] if len(argv) > 2 and argv[2] else None
            duration = float(argv[3]) if len(argv) > 3 else 0.0
            emit({"result": _segments(wav_path, models_dir, duration)})
            return 0
        emit({"error": f"Chế độ lạ: {mode}"})
        return 1
    except Exception as e:  # noqa: BLE001
        emit({"error": str(e)})
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
