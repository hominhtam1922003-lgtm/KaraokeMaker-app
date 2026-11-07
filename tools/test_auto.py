"""Kiểm tích hợp TỰ ĐỘNG TOÀN PHẦN qua HTTP với faster-whisper GIẢ (stub):
server thật + tách beat nhanh thật + render thật, chỉ phần nghe là stub.
Chạy: python tools/test_auto.py"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
STUB = "/tmp/fwstub2"
FAILS = []


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
    sig = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.2 * np.sin(2 * np.pi * 220 * t)
    voice = 0.25 * np.sin(2 * np.pi * (520 + 40 * np.sin(2 * np.pi * 2 * t)) * t)
    mono = np.clip(sig + voice, -0.95, 0.95)
    stereo = np.stack([mono, mono * 0.98 + 0.02 * voice], axis=1)
    with wave.open("/tmp/ktest/mix.wav", "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((stereo * 32767).astype("<i2").tobytes())


def make_stub():
    os.makedirs(STUB, exist_ok=True)
    with open(os.path.join(STUB, "faster_whisper.py"), "w") as f:
        f.write('''
class _W:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end
class _Seg:
    def __init__(self, text, words, start, end):
        self.text, self.words, self.start, self.end = text, words, start, end
class WhisperModel:
    def __init__(self, *a, **k): pass
    def transcribe(self, path, **kw):
        lines = ["Ngày thay đêm vội trôi giấc mơ êm đềm",
                 "Tôi lênh đênh trên biển vắng",
                 "Hoàng hôn chờ em chưa buông nắng"]
        segs, t = [], 2.0
        for ln in lines:
            ws = []
            for w in ln.split():
                ws.append(_W(" " + w, t, t + 0.3)); t += 0.32
            segs.append(_Seg(" " + ln, ws, ws[0].start, ws[-1].end)); t += 0.7
        return iter(segs), {}
''')


def req(base, method, path, body=None, headers=None, raw=False):
    data = body if raw or body is None else json.dumps(body).encode()
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            b = resp.read()
            return resp.status, (b if raw else json.loads(b or b"{}"))
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:
            return e.code, {}


def wait_job(base, jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _s, job = req(base, "GET", f"/api/job/{jid}")
        if job.get("status") in ("done", "error"):
            return job
        time.sleep(0.7)
    return {"status": "timeout"}


def main():
    make_fixture()
    make_stub()
    env = dict(os.environ, PYTHONPATH=STUB, KARAOKE_NO_BROWSER="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        line = proc.stdout.readline()
        base = line.split("tại ")[-1].strip().rstrip("/")
        print("server:", base)

        st, r = req(base, "POST", "/api/auto-all", {"sep_mode": "fast"})
        check("auto-all chưa có bài -> 400", st == 400, str(r))

        with open("/tmp/ktest/mix.wav", "rb") as f:
            st, r = req(base, "POST", "/api/upload-song", f.read(),
                        {"X-File-Name": "mix.wav"}, raw=True)
        # upload-song trả JSON dù raw body gửi lên
        if isinstance(r, bytes):
            r = json.loads(r)
        check("upload ok", st == 200 and r.get("ok"), str(r))

        st, r = req(base, "POST", "/api/auto-all", {
            "lyrics": None, "sep_mode": "fast",
            "style": {"two_line": True, "effect": "sweep"},
            "title": "Bài Test Tự Động",
            "bg": {"type": "gradient", "value": "biensau"}, "guide": 0})
        check("auto-all nhận job", st == 200 and "job" in r, str(r))
        jid = r["job"]

        st2, r2 = req(base, "POST", "/api/separate", {"mode": "fast"})
        check("đang bận: separate -> 409", st2 == 409, str(r2))

        job = wait_job(base, jid)
        check("auto-all done", job.get("status") == "done", str(job.get("error")))
        res = job.get("result") or {}
        check("source=ai (tự chép lời)", res.get("source") == "ai", str(res))
        check("có >= 3 câu", (res.get("count") or 0) >= 3, str(res.get("count")))
        lines = res.get("lines") or []
        check("câu có words từng từ",
              bool(lines) and all(l.get("words") for l in lines))
        st, vid = req(base, "GET", "/api/video", raw=True)
        check("video tải được & > 50KB", st == 200 and len(vid) > 50000,
              f"{st} {len(vid) if isinstance(vid, bytes) else 0}")

        ass_path = os.path.join(ROOT, "work", "session", "lyrics.ass")
        ass = open(ass_path, encoding="utf-8").read()
        check("ASS có \\kf + KaraNext + KaraTitle + tên bài",
              "\\kf" in ass and "KaraNext" in ass and "KaraTitle" in ass
              and "Bài Test Tự Động" in ass)

        st, r = req(base, "POST", "/api/auto-all", {
            "lyrics": ["Ngày thay đêm vội trôi giấc mơ êm đềm",
                       "Tôi lênh đênh trên biển vắng",
                       "Hoàng hôn chờ em chưa buông nắng"],
            "sep_mode": "fast", "style": {}, "bg": {"type": "color",
                                                    "value": "#0b0e1a"}})
        job = wait_job(base, r["job"])
        res = job.get("result") or {}
        check("user lyrics: source=user & matched cao",
              job.get("status") == "done" and res.get("source") == "user"
              and (res.get("matched") or 0) >= 0.9, str(res)[:200])
    finally:
        proc.terminate()
    print()
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
