"""Kiểm cơ chế WHISPER TIẾN TRÌNH RIÊNG — thuốc chữa sự cố 1.1.0 "bấm Tự
căn, thanh đứng 3% rồi im luôn" (AI sập kéo cả app chết trong im lặng):
- stub tốt: chép lời qua worker con chạy đúng, có đoạn + từ.
- stub SẬP CỨNG (os._exit): transcribe báo lỗi rõ ràng, KHÔNG chết theo.
- stub thiếu thư viện: lỗi tiếng Việt sạch.
- CẤP SERVER: worker sập giữa job tự căn -> job báo error, server VẪN SỐNG
  (đây là ca bệnh thật của người dùng).
Chạy: python tools/test_whisper.py"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
FAILS = []

GOOD = '''
class _W:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end
class _Seg:
    def __init__(self, text, words, start, end):
        self.text, self.words, self.start, self.end = text, words, start, end
class WhisperModel:
    def __init__(self, *a, **k): pass
    def transcribe(self, path, **kw):
        lines = ["Ngày thay đêm vội trôi", "Tôi lênh đênh trên biển vắng"]
        segs, t = [], 2.0
        for ln in lines:
            ws = []
            for w in ln.split():
                ws.append(_W(" " + w, t, t + 0.3)); t += 0.32
            segs.append(_Seg(" " + ln, ws, ws[0].start, ws[-1].end)); t += 0.7
        return iter(segs), {}
'''
CRASH = '''
import os
class WhisperModel:
    def __init__(self, *a, **k):
        os._exit(3)
'''
NOLIB = 'raise ImportError("No module named faster_whisper (stub)")\n'
# Treo cứng khi xin giờ từng từ (đúng ca bệnh máy thật 07/11); chế độ đoạn
# (không giờ từng từ) thì chạy được nhưng không trả từ nào.
HANG = '''
import time
class _Seg:
    def __init__(self, text, start, end):
        self.text, self.words, self.start, self.end = text, None, start, end
class WhisperModel:
    def __init__(self, *a, **k): pass
    def transcribe(self, path, **kw):
        if kw.get("word_timestamps"):
            time.sleep(3600)
        segs = [_Seg(" Ngày thay đêm vội trôi", 2.0, 4.4),
                _Seg(" Tôi lênh đênh trên biển vắng", 5.0, 8.2)]
        return iter(segs), {}
'''
# Chạy chậm nhưng còn sống: ra 1 đoạn, ngủ 6 giây, ra đoạn nữa.
SLOW = '''
import time
class _W:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end
class _Seg:
    def __init__(self, text, words, start, end):
        self.text, self.words, self.start, self.end = text, words, start, end
def _mk(ln, t0):
    ws, t = [], t0
    for w in ln.split():
        ws.append(_W(" " + w, t, t + 0.3)); t += 0.32
    return _Seg(" " + ln, ws, ws[0].start, ws[-1].end)
class WhisperModel:
    def __init__(self, *a, **k): pass
    def transcribe(self, path, **kw):
        def gen():
            yield _mk("Ngày thay đêm vội trôi", 2.0)
            time.sleep(6)
            yield _mk("Tôi lênh đênh trên biển vắng", 5.0)
        return gen(), {}
'''


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def make_fixture():
    import numpy as np
    import wave
    os.makedirs("/tmp/ktest", exist_ok=True)
    sr = 22050
    t = np.arange(int(sr * 12)) / sr
    sig = 0.3 * np.sin(2 * np.pi * 110 * t)
    with wave.open("/tmp/ktest/mix.wav", "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.stack([sig, sig], axis=1).astype("<f4").tobytes()
                      if False else (np.clip(np.stack([sig, sig], axis=1),
                                             -0.95, 0.95) * 32767
                                     ).astype("<i2").tobytes())


def write_stub(d, code):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "faster_whisper.py"), "w") as f:
        f.write(code)


def unit_cases():
    from karaoke import align
    wav = "/tmp/ktest/mix.wav"
    models = "/tmp/fwmodels_test"
    # 1) stub tốt
    write_stub("/tmp/fwstub_good", GOOD)
    os.environ["PYTHONPATH"] = "/tmp/fwstub_good"
    segs = align.transcribe_segments(wav, 12.0, None, models)
    check("worker tốt: có đoạn + từ",
          len(segs) >= 2 and segs[0]["words"] and segs[0]["text"])
    # 2) stub sập cứng
    write_stub("/tmp/fwstub_crash", CRASH)
    os.environ["PYTHONPATH"] = "/tmp/fwstub_crash"
    try:
        align.transcribe_segments(wav, 12.0, None, models)
        check("worker sập: phải ném lỗi", False)
    except RuntimeError as e:
        check("worker sập: lỗi rõ 'sập giữa chừng'", "sập giữa chừng" in str(e),
              str(e)[:120])
    # 3) thiếu thư viện
    write_stub("/tmp/fwstub_nolib", NOLIB)
    os.environ["PYTHONPATH"] = "/tmp/fwstub_nolib"
    try:
        align.transcribe_segments(wav, 12.0, None, models)
        check("thiếu thư viện: phải ném lỗi", False)
    except RuntimeError as e:
        check("thiếu thư viện: báo tiếng Việt", "thiếu thư viện" in str(e),
              str(e)[:120])
    # 4) load_model_only qua worker tốt
    os.environ["PYTHONPATH"] = "/tmp/fwstub_good"
    try:
        align.load_model_only(models)
        check("load_model_only qua worker: ok", True)
    except Exception as e:  # noqa: BLE001
        check("load_model_only qua worker: ok", False, str(e)[:120])
    # 5) THANG DỰ PHÒNG: treo ở chế độ giờ-từ -> tự xuống chế độ đoạn và
    # tổng hợp giờ cho từng từ (ca bệnh thật: đứng 47,2% suốt 12 phút).
    write_stub("/tmp/fwstub_hang", HANG)
    os.environ["PYTHONPATH"] = "/tmp/fwstub_hang"
    os.environ["KARAOKE_WHISPER_STALL_S"] = "3"
    os.environ["KARAOKE_WHISPER_HEARTBEAT_S"] = "1"
    t0 = time.time()
    try:
        segs = align.transcribe_segments(wav, 12.0, None, models)
        dt = time.time() - t0
        ok_words = bool(segs and segs[0]["words"]) and all(
            segs[0]["start"] <= w["start"] < w["end"] <= segs[0]["end"] + 0.01
            for w in segs[0]["words"])
        check("thang dự phòng: treo -> vẫn ra đoạn + từ tổng hợp",
              len(segs) == 2 and ok_words, f"{dt:.0f}s")
        check("thang dự phòng: tổng thời gian bị chặn (không treo 12 phút)",
              dt < 60, f"{dt:.0f}s")
    except Exception as e:  # noqa: BLE001
        check("thang dự phòng: treo -> vẫn ra đoạn + từ tổng hợp", False,
              str(e)[:150])
    # 6) NHỊP TIM: worker chậm nhưng sống -> client tự phát "Vẫn đang..."
    write_stub("/tmp/fwstub_slow", SLOW)
    os.environ["PYTHONPATH"] = "/tmp/fwstub_slow"
    os.environ["KARAOKE_WHISPER_STALL_S"] = "30"
    os.environ["KARAOKE_WHISPER_HEARTBEAT_S"] = "2"
    labels = []
    try:
        segs = align.transcribe_segments(
            wav, 12.0, lambda p, l="": labels.append(l), models)
        check("nhịp tim: có nhãn 'Vẫn đang' khi worker im lặng",
              any("Vẫn đang" in l for l in labels), str(labels)[:150])
        check("nhịp tim: đoạn vẫn ra đủ", len(segs) == 2)
    except Exception as e:  # noqa: BLE001
        check("nhịp tim: có nhãn 'Vẫn đang' khi worker im lặng", False,
              str(e)[:150])
    os.environ.pop("KARAOKE_WHISPER_STALL_S", None)
    os.environ.pop("KARAOKE_WHISPER_HEARTBEAT_S", None)


def req(base, method, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(base + path, data=data, method=method)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            b = resp.read()
            try:
                return resp.status, json.loads(b or b"{}")
            except Exception:
                return resp.status, b
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:
            return e.code, {}


def server_case():
    write_stub("/tmp/fwstub_crash", CRASH)
    env = dict(os.environ, PYTHONPATH="/tmp/fwstub_crash",
               KARAOKE_NO_BROWSER="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        base = proc.stdout.readline().split("tại ")[-1].strip().rstrip("/")
        with open("/tmp/ktest/mix.wav", "rb") as f:
            payload = f.read()
        st, r = req(base, "POST", "/api/upload-song", raw=payload,
                    headers={"X-File-Name": "mix.wav"})
        check("server: nạp bài ok", st == 200, str(r)[:100])
        st, r = req(base, "POST", "/api/auto-align",
                    {"lines": ["Ngày thay đêm vội trôi",
                               "Tôi lênh đênh trên biển vắng"]})
        check("server: nhận job tự căn", st == 200 and "job" in r, str(r)[:100])
        job = {}
        t0 = time.time()
        while time.time() - t0 < 90:
            _s, job = req(base, "GET", f"/api/job/{r['job']}")
            if job.get("status") in ("done", "error"):
                break
            time.sleep(0.5)
        check("server: job thành error (không treo)",
              job.get("status") == "error", str(job)[:150])
        check("server: lỗi nhắc rõ AI sập",
              "sập" in str(job.get("error") or ""), str(job.get("error"))[:150])
        st, _r = req(base, "GET", "/api/state")
        check("server: VẪN SỐNG sau khi AI sập", st == 200)
        check("server: tiến trình chưa chết", proc.poll() is None)
    finally:
        proc.terminate()


def main():
    make_fixture()
    unit_cases()
    server_case()
    print()
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
