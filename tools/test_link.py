"""Kiểm tích hợp HỆ THỐNG TỰ HÀNH (link YouTube -> video) qua HTTP với
yt-dlp GIẢ (stub ghi file fixture) + faster-whisper GIẢ. Phần tải thật từ
YouTube phụ thuộc IP/mạng từng máy — kiểm riêng trên máy người dùng.
Chạy: python tools/test_link.py"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
STUB = "/tmp/fwstub3"
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


def make_stubs():
    os.makedirs(STUB, exist_ok=True)
    with open(os.path.join(STUB, "yt_dlp.py"), "w") as f:
        f.write('''
import os, shutil
class YoutubeDL:
    def __init__(self, opts):
        self.opts = opts
        self._path = opts["outtmpl"].replace("%(ext)s", "m4a")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=True):
        for h in self.opts.get("progress_hooks", []):
            h({"status": "downloading", "downloaded_bytes": 50,
               "total_bytes": 100})
            h({"status": "finished"})
        shutil.copyfile("/tmp/ktest/mix.wav", self._path)
        return {"title": "B\\u00e0i Stub (OST) - Ca S\\u0129 Test"}
    def prepare_filename(self, info):
        return self._path
''')
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


def req(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
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
    make_stubs()
    env = dict(os.environ, PYTHONPATH=STUB, KARAOKE_NO_BROWSER="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        base = proc.stdout.readline().split("tại ")[-1].strip().rstrip("/")
        print("server:", base)

        st, r = req(base, "POST", "/api/auto-link", {"url": "khong phai link"})
        check("link rác -> 400 ngay", st == 400, str(r))
        st, r = req(base, "POST", "/api/auto-link",
                    {"url": "https://vimeo.com/123456"})
        check("link không phải YouTube -> 400", st == 400, str(r))

        st, r = req(base, "POST", "/api/auto-link", {
            "url": "https://youtu.be/GEleN2E5yTE?si=xyz",
            "want_video": False, "sep_mode": "fast",
            "style": {"two_line": True}, "bg": {"type": "gradient",
                                                "value": "demtim"}})
        check("auto-link nhận job", st == 200 and "job" in r, str(r))
        job = wait_job(base, r["job"])
        check("auto-link done", job.get("status") == "done",
              str(job.get("error")))
        res = job.get("result") or {}
        check("thành phẩm: source=ai, >=3 câu",
              res.get("source") == "ai" and (res.get("count") or 0) >= 3,
              str(res)[:160])
        st, vid = req(base, "GET", "/api/video")
        check("video thành phẩm tải được", st == 200 and len(vid) > 50000)
        st, song = req(base, "GET", "/api/audio/song")
        check("bài đã nạp từ link (nghe lại được)", st == 200 and len(song) > 10000)
        ass = open(os.path.join(ROOT, "work", "session", "lyrics.ass"),
                   encoding="utf-8").read()
        check("thẻ tên bài = tiêu đề YouTube",
              "Bài Stub (OST) - Ca Sĩ Test" in ass)
    finally:
        proc.terminate()
    print()
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
