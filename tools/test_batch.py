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
STUB2 = "/tmp/fwstub_batch2"
WORKDIR = os.path.join(ROOT, "work")
BATCH_JSON = os.path.join(WORKDIR, "batch.json")
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


def make_stubs2():
    """Stub như STUB nhưng yt-dlp NGỦ 10s khi tải — để pha lưu bền có
    cửa sổ chắc chắn: tắt app giữa chừng khi batch còn bài dở."""
    os.makedirs(STUB2, exist_ok=True)
    with open(os.path.join(STUB2, "yt_dlp.py"), "w") as f:
        f.write('''
import os, shutil, time
class YoutubeDL:
    def __init__(self, opts):
        self.opts = opts
        self._path = opts["outtmpl"].replace("%(ext)s", "m4a")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=True):
        time.sleep(10)
        for h in self.opts.get("progress_hooks", []):
            h({"status": "downloading", "downloaded_bytes": 50,
               "total_bytes": 100})
            h({"status": "finished"})
        shutil.copyfile("/tmp/ktest/mix.wav", self._path)
        return {"title": "B\\u00e0i Stub Ch\\u1eadm"}
    def prepare_filename(self, info):
        return self._path
''')
    with open(os.path.join(STUB2, "faster_whisper.py"), "w") as f:
        f.write(open(os.path.join(STUB, "faster_whisper.py")).read())


def start_server(stub):
    env = dict(os.environ, PYTHONPATH=stub, KARAOKE_NO_BROWSER="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"], cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = ""
    for _ in range(50):  # quét tới dòng banner (log khác có thể chen trước)
        line = proc.stdout.readline()
        if not line:
            break
        if "đang chạy tại " in line:
            base = line.split("tại ")[-1].strip().rstrip("/")
            break
    print("server:", base)
    return proc, base


def gate_unit_phase():
    """Kiểm CỔNG SONG SONG theo chế độ tách (unit, không qua HTTP):
    monkeypatch _run_batch_item ghi lại độ song song thật — mode ai
    tối đa 1 bài cùng lúc, mode fast tối đa 2, tổng tối đa 2 worker."""
    script = os.path.join("/tmp", "test_batch_gate.py")
    with open(script, "w") as f:
        f.write('''
import os, sys, threading, time
sys.path.insert(0, r"''' + os.path.abspath(ROOT) + '''")
import app

app._load_batch()  # như main(): khôi phục trước để _save_batch không đè mất

stats = {"cur": {"ai": 0, "fast": 0}, "max": {"ai": 0, "fast": 0},
         "cur_t": 0, "max_t": 0}
lk = threading.Lock()

def fake_run(item, opts):
    mode = opts.get("sep_mode", "ai")
    with lk:
        stats["cur"][mode] += 1
        stats["cur_t"] += 1
        stats["max"][mode] = max(stats["max"][mode], stats["cur"][mode])
        stats["max_t"] = max(stats["max_t"], stats["cur_t"])
    time.sleep(0.6)
    with lk:
        stats["cur"][mode] -= 1
        stats["cur_t"] -= 1
    return {"lines": []}

app._run_batch_item = fake_run
app._ensure_batch_workers()
now = time.time()
ids = []
for mode, n in (("ai", 3), ("fast", 3)):
    for k in range(n):
        iid = f"gate{mode}{k}"
        item = {"id": iid, "url": "https://youtu.be/GEleN2E5yTE",
                "title": iid, "kind": "link", "status": "queued",
                "progress": 0.0, "label": "", "error": None,
                "project_id": None, "interrupted": False, "cleaned": [],
                "created_at": now, "updated_at": now, "finished_at": None,
                "_opts": {"want_video": False, "sep_mode": mode,
                          "style": {}, "guide": 0,
                          "bg": {"type": "gradient", "value": "demtim"}},
                "_ctx": app.new_ctx(os.path.join(app.ROOT, "batch", iid))}
        with app.LOCK:
            app.BATCH[iid] = item
            app.BATCH_ORDER.append(iid)
        app._enqueue_batch(iid)
        ids.append(iid)
app._save_batch()
t0 = time.time()
while time.time() - t0 < 60:
    if all(app.BATCH[i]["status"] in ("done", "error") for i in ids):
        break
    time.sleep(0.2)
bad = [(i, app.BATCH[i]["status"], app.BATCH[i].get("error")) for i in ids
       if app.BATCH[i]["status"] != "done"]
print("GATE-RESULT", stats["max"], "total", stats["max_t"], "bad", bad)
ok = (not bad and stats["max"]["ai"] == 1
      and stats["max"]["fast"] <= 2 and stats["max_t"] <= 2)
print("GATE-OK" if ok else "GATE-FAIL")
sys.exit(0 if ok else 1)
''')
    r = subprocess.run([sys.executable, script], cwd=ROOT,
                       capture_output=True, text=True, timeout=180)
    print((r.stdout or "").strip()[-400:])
    if r.returncode != 0:
        print((r.stderr or "").strip()[-400:])
    check("cổng song song: ai<=1, fast<=2, tổng<=2, mọi bài done",
          r.returncode == 0 and "GATE-OK" in (r.stdout or ""))


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


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:  # noqa: BLE001
        proc.kill()


def get_items(base, ids=None):
    _s, data, _h = req(base, "GET", "/api/batch")
    items = data.get("items", []) if isinstance(data, dict) else []
    if ids is not None:
        items = [i for i in items if i["id"] in ids]
    return items


def _leftovers(d):
    names = set(os.listdir(d)) if os.path.isdir(d) else set()
    bad = [n for n in names
           if n in ("song.wav", "inst.wav", "vocal.wav", "mixed.wav")
           or n.startswith("yt_src.") or n.endswith(".pcm16k")
           or n.startswith("grad_") or n.startswith("gradanim_")]
    return names, bad


def persist_phase():
    """LƯU BỀN + CHẠY TIẾP: nộp 4 bài (stub tải chậm 10s), tắt app
    giữa chừng, mở lại -> bài dở hiện lại dạng chờ + cờ interrupted,
    Chạy tiếp chỉ làm nốt bài dở, bài done không chạy lại."""
    proc, base = start_server(STUB2)
    ids = []
    snap = []
    try:
        st, r, _h = req(base, "POST", "/api/batch", {
            "urls": ["https://youtu.be/GEleN2E5yTE"] * 4,
            "sep_mode": "fast", "style": {},
            "bg": {"type": "gradient", "value": "demtim"}})
        check("lưu bền: nộp 4 bài",
              st == 200 and len(r.get("items", [])) == 4, str(r)[:120])
        ids = list(r.get("items", []))
        idset = set(ids)
        t0 = time.time()
        while time.time() - t0 < 240:
            snap = get_items(base, idset)
            ndone = sum(1 for i in snap if i["status"] == "done")
            if len(snap) == 4 and 0 < ndone < 4:
                break
            time.sleep(1.0)
        ndone = sum(1 for i in snap if i["status"] == "done")
        check("lưu bền: bắt được trạng thái dở dang (có done, có dở)",
              len(snap) == 4 and 0 < ndone < 4,
              str([i["status"] for i in snap]))
    finally:
        stop_server(proc)
    if len(ids) != 4:
        check("lưu bền: pha khôi phục (thiếu bài nộp)", False)
        return
    idset = set(ids)
    try:
        saved = json.load(open(BATCH_JSON, encoding="utf-8"))
        recs = {x["id"]: x for x in saved.get("items", [])
                if x.get("id") in idset}
    except Exception as e:  # noqa: BLE001
        recs = {}
        check("lưu bền: đọc được batch.json", False, str(e))
    check("lưu bền: batch.json có đủ 4 bài", len(recs) == 4,
          str(list(recs)))
    fields = ("kind", "url", "status", "opts", "project_id",
              "created_at", "updated_at", "finished_at")
    check("lưu bền: mỗi bài đủ trường + opts.sep_mode=fast",
          len(recs) == 4 and all(
              all(k in recs[i] for k in fields)
              and recs[i]["opts"].get("sep_mode") == "fast"
              for i in ids),
          str(recs.get(ids[0]))[:200] if recs else "")
    done_ids = [i for i in ids if recs.get(i, {}).get("status") == "done"]
    todo_ids = [i for i in ids if recs.get(i, {}).get("status")
                in ("pending", "running")]
    check("lưu bền: trạng thái ghi đúng (done có project_id)",
          bool(done_ids) and bool(todo_ids) and all(
              recs[i].get("project_id") for i in done_ids),
          str({i: recs.get(i, {}).get("status") for i in ids}))
    was_running = [i for i in todo_ids
                   if recs[i].get("status") == "running"]
    mtimes = {}
    for i in done_ids:
        p = os.path.join(WORKDIR, "batch", i, "karaoke.mp4")
        if os.path.exists(p):
            mtimes[i] = os.path.getmtime(p)
    proc, base = start_server(STUB2)
    try:
        snap = {i["id"]: i for i in get_items(base, idset)}
        check("khôi phục: đủ 4 bài hiện lại", len(snap) == 4,
              str(list(snap)))
        check("khôi phục: done giữ done, bài dở thành chờ chạy tiếp",
              all(snap[i]["status"] == "done" for i in done_ids)
              and all(snap[i]["status"] == "queued" for i in todo_ids),
              str({i: snap.get(i, {}).get("status") for i in ids}))
        if was_running:
            check("khôi phục: bài đang chạy dở gắn cờ interrupted",
                  all(snap[i].get("interrupted") for i in was_running),
                  str({i: snap.get(i, {}).get("interrupted")
                       for i in was_running}))
        if done_ids:
            st, vid, _h = req(base, "GET",
                              f"/api/batch/{done_ids[0]}/video")
            check("khôi phục: video bài done xem lại được",
                  st == 200 and len(vid) > 50000, f"status={st}")
        st, r, _h = req(base, "POST", "/api/batch/resume", {})
        check("chạy tiếp: xếp đúng số bài dở",
              st == 200 and r.get("resumed") == len(todo_ids),
              str(r)[:100])
        st, r, _h = req(base, "POST", "/api/batch/resume", {})
        check("chạy tiếp: bấm lần 2 không xếp trùng",
              st == 200 and r.get("resumed") == 0, str(r)[:100])
        snap = []
        t0 = time.time()
        while time.time() - t0 < 300:
            snap = get_items(base, idset)
            if len(snap) == 4 and all(
                    i["status"] in ("done", "error") for i in snap):
                break
            time.sleep(1.5)
        check("chạy tiếp: mọi bài dở hoàn thành",
              len(snap) == 4
              and all(i["status"] == "done" for i in snap),
              str([(i["status"], i.get("error")) for i in snap])[:200])
        check("chạy tiếp: bài done cũ KHÔNG chạy lại (mtime nguyên)",
              bool(mtimes) and all(
                  os.path.getmtime(os.path.join(
                      WORKDIR, "batch", i, "karaoke.mp4")) == mtimes[i]
                  for i in mtimes),
              str(mtimes))
        for i in todo_ids:
            names, bad = _leftovers(os.path.join(WORKDIR, "batch", i))
            check(f"chạy tiếp: dọn đĩa bài {i[:6]}",
                  "karaoke.mp4" in names and "lyrics.ass" in names
                  and not bad, str(sorted(names))[:150])
        # Bài lỗi: resume bỏ qua, file chẩn đoán giữ nguyên
        st, r, _h = req_raw(base, "/api/batch-file",
                            b"day khong phai file nhac", {
                                "X-File-Name": urllib.parse.quote(
                                    "File Rac.wav"),
                                "X-Batch-Opts": json.dumps({
                                    "sep_mode": "fast", "style": {},
                                    "bg": {"type": "gradient",
                                           "value": "neon"}})})
        fid = r.get("item") if isinstance(r, dict) else None
        check("bài lỗi: nhận file rác", st == 200 and bool(fid),
              str(r)[:100])
        fitem = None
        t0 = time.time()
        while time.time() - t0 < 120 and fid:
            fitem = next((i for i in get_items(base)
                          if i["id"] == fid), None)
            if fitem and fitem["status"] in ("done", "error"):
                break
            time.sleep(1.0)
        check("bài lỗi: thành mục lỗi",
              bool(fitem) and fitem["status"] == "error",
              str(fitem)[:150])
        if fid and fitem and fitem["status"] == "error":
            d = os.path.join(WORKDIR, "batch", fid)
            os.makedirs(d, exist_ok=True)
            for n in ("song.wav", "vocal.wav"):
                with open(os.path.join(d, n), "wb") as fh:
                    fh.write(b"sentinel")
            st, r, _h = req(base, "POST", "/api/batch/resume", {})
            kept = all(os.path.exists(os.path.join(d, n))
                       for n in ("song.wav", "vocal.wav"))
            fitem2 = next((i for i in get_items(base)
                           if i["id"] == fid), None)
            check("bài lỗi: resume bỏ qua + giữ file chẩn đoán",
                  st == 200 and r.get("resumed") == 0 and kept
                  and bool(fitem2) and fitem2["status"] == "error",
                  str(r)[:80])
    finally:
        stop_server(proc)


def corrupt_phase():
    """batch.json hỏng (JSON rác): app vẫn mở bình thường, coi như
    batch trống và giữ file hỏng sang tên batch.json.corrupt."""
    with open(BATCH_JSON, "w", encoding="utf-8") as f:
        f.write("DAY LA JSON RAC {{{ khong parse duoc")
    proc, base = start_server(STUB2)
    try:
        st, data, _h = req(base, "GET", "/api/batch")
        check("batch.json hỏng: app vẫn chạy, batch coi như trống",
              st == 200 and data.get("items") == [], str(data)[:120])
        corrupt = BATCH_JSON + ".corrupt"
        ok = os.path.exists(corrupt) and "JSON RAC" in open(
            corrupt, encoding="utf-8").read()
        check("batch.json hỏng: file được giữ sang .corrupt", ok)
    finally:
        stop_server(proc)


def main():
    make_fixture()
    make_stubs()
    make_stubs2()
    gate_unit_phase()
    proc, base = start_server(STUB)
    try:

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
        for i in done:
            names, bad = _leftovers(os.path.join(WORKDIR, "batch",
                                                 i["id"]))
            check(f"dọn đĩa bài {i['id'][:6]}: còn video + ass, "
                  "hết file trung gian",
                  "karaoke.mp4" in names and "lyrics.ass" in names
                  and not bad, str(sorted(names))[:150])

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
        stop_server(proc)
    persist_phase()
    corrupt_phase()
    print()
    print("FAILED:", FAILS if FAILS else "none")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
