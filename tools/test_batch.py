"""Kiểm HÀNG LOẠT qua HTTP: dán nhiều link -> chạy song song -> mỗi bài một
video riêng; link hỏng thành mục lỗi rõ ràng; các ca biên (rỗng / quá nhiều /
toàn link hỏng) trả 400. yt-dlp + faster-whisper đều là stub trên PYTHONPATH
(worker Whisper là tiến trình con — vẫn thừa hưởng PYTHONPATH).
Chạy: python tools/test_batch.py"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
STUB = "/tmp/fwstub_batch"
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
    stereo = np.stack([sig, sig * 0.98], axis=1)
    with wave.open("/tmp/ktest/mix.wav", "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(stereo, -0.95, 0.95) * 32767
                       ).astype("<i2").tobytes())


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
        return {"title": "B\\u00e0i Stub (OST)"}
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
                return resp.status, json.loads(b or b"{}"), resp.headers
            except Exception:
                return resp.status, b, resp.headers
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}"), e.headers
        except Exception:
            return e.code, {}, e.headers


def req_raw(base, path, data, headers):
    r = urllib.request.Request(base + path, data=data, method="POST")
    for k, v in headers.items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            b = resp.read()
            try:
                return resp.status, json.loads(b or b"{}"), resp.headers
            except Exception:
                return resp.status, b, resp.headers
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}"), e.headers
        except Exception:
            return e.code, {}, e.headers


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

        st, r, _h = req(base, "POST", "/api/batch", {"urls": []})
        check("batch rỗng -> 400", st == 400, str(r)[:100])
        st, r, _h = req(base, "POST", "/api/batch",
                        {"urls": ["https://youtu.be/GEleN2E5yTE"] * 21})
        check("batch 21 link -> 400", st == 400, str(r)[:100])
        st, r, _h = req(base, "POST", "/api/batch",
                        {"urls": ["link rac", "cung rac"]})
        check("batch toàn link hỏng -> 400", st == 400, str(r)[:100])

        st, r, _h = req(base, "POST", "/api/batch", {
            "urls": ["https://youtu.be/GEleN2E5yTE?si=x", "link rac",
                     "https://www.youtube.com/watch?v=GEleN2E5yTE"],
            "sep_mode": "fast", "style": {},
            "bg": {"type": "gradient", "value": "demtim"}})
        check("batch 3 link nhận", st == 200 and len(r.get("items", [])) == 3,
              str(r)[:120])
        my_ids = set(r.get("items", []))

        items = []
        t0 = time.time()
        while time.time() - t0 < 300:
            _s, data, _h = req(base, "GET", "/api/batch")
            items = [i for i in data.get("items", []) if i["id"] in my_ids]
            if len(items) == 3 and all(
                    i["status"] in ("done", "error") for i in items):
                break
            time.sleep(1.5)
        done = [i for i in items if i["status"] == "done"]
        errs = [i for i in items if i["status"] == "error"]
        check("batch: 2 bài xong", len(done) == 2,
              str([(i["status"], i.get("error")) for i in items])[:200])
        check("batch: 1 mục lỗi link rác hiện rõ",
              len(errs) == 1 and "không hợp lệ" in (errs[0].get("error") or ""),
              str(errs)[:150])
        check("batch: bài xong có tiêu đề từ YouTube",
              all(i.get("title") == "Bài Stub (OST)" for i in done))
        for i in done:
            st, vid, _h = req(base, "GET", f"/api/batch/{i['id']}/video")
            check(f"batch: video bài {i['id'][:6]} tải được",
                  st == 200 and len(vid) > 50000)
            st, _b, hdrs = req(base, "GET", f"/api/batch/{i['id']}/download")
            cd = hdrs.get("Content-Disposition") or ""
            check(f"batch: download đúng tên .mp4 ({i['id'][:6]})",
                  st == 200 and ".mp4" in cd, cd[:80])
        st, _r, _h = req(base, "GET",
                         f"/api/batch/{errs[0]['id']}/video" if errs else "/x")
        check("batch: bài lỗi không có video -> 404", st == 404)

        # --- v3: hàng loạt từ FILE trên máy + lưu video vào máy ---
        raw = open("/tmp/ktest/mix.wav", "rb").read()
        st, r, _h = req_raw(base, "/api/batch-file", raw, {
            "X-File-Name": urllib.parse.quote("Bài File Test.wav"),
            "X-Batch-Opts": json.dumps({
                "sep_mode": "fast", "style": {},
                "bg": {"type": "gradient", "value": "neon"}})})
        check("batch-file: nhận file", st == 200 and bool(r.get("item")),
              str(r)[:100])
        fid = r.get("item")
        fitem = None
        t0 = time.time()
        while time.time() - t0 < 300:
            _s, data, _h = req(base, "GET", "/api/batch")
            fitem = next((i for i in data.get("items", [])
                          if i["id"] == fid), None)
            if fitem and fitem["status"] in ("done", "error"):
                break
            time.sleep(1.5)
        check("batch-file: chạy xong", bool(fitem) and fitem["status"] == "done",
              str(fitem)[:200])
        check("batch-file: kind=file + title từ tên file",
              bool(fitem) and fitem.get("kind") == "file"
              and fitem.get("title") == "Bài File Test", str(fitem)[:150])
        st, r, _h = req(base, "POST", f"/api/batch/{fid}/save", {})
        saved = (r.get("path") or "") if isinstance(r, dict) else ""
        check("batch-file: lưu video vào máy",
              st == 200 and saved.endswith(".mp4") and os.path.exists(saved),
              str(r)[:120])
        st, r, _h = req(base, "POST", "/api/open-folder", {})
        check("open-folder ok", st == 200 and r.get("ok") is True, str(r)[:80])
        st, r, _h = req(base, "POST", "/api/save-video", {})
        check("save-video chưa có video -> 400", st == 400, str(r)[:80])
    finally:
        proc.terminate()
    print()
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
