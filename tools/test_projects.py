"""Lưới kiểm v4: tầng DỰ ÁN (CRUD + project.json hỏng + id ký tự lạ),
WAVEFORM peaks (file im lặng / file ngắn / chuẩn hoá), HÀNG ĐỢI XUẤT
(validate + render thật), MẪU CẤU HÌNH (preset). Server chạy in-process
trên cổng riêng, PROJECTS_DIR/PRESETS_FILE được trỏ sang /tmp để không
bẩn thư mục work thật.

Chạy: .venv/bin/python tools/test_projects.py
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np  # noqa: E402

import app as appmod  # noqa: E402

TMP = "/tmp/kproj"
os.makedirs(TMP, exist_ok=True)
appmod.PROJECTS_DIR = os.path.join(TMP, "projects")
os.makedirs(appmod.PROJECTS_DIR, exist_ok=True)
appmod.PRESETS_FILE = os.path.join(TMP, "presets.json")
if os.path.exists(appmod.PRESETS_FILE):
    os.remove(appmod.PRESETS_FILE)

PORT = 8773
BASE = f"http://127.0.0.1:{PORT}"
RESULTS = []


def scenario(name):
    def deco(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"FAIL  {name} -> {type(e).__name__}: {e}")
        return fn
    return deco


def http(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method, data=body,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def http_json(method, path, obj=None, headers=None):
    body = None
    hdr = dict(headers or {})
    if obj is not None:
        body = obj if isinstance(obj, (bytes, bytearray)) else \
            json.dumps(obj).encode("utf-8")
        hdr.setdefault("Content-Type", "application/json")
    st, raw, _h = http(method, path, body, hdr)
    try:
        return st, json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return st, {"_raw": raw[:200]}


def write_wav(path, seconds=2.0, sr=44100, kind="tone", freq=440.0):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    if kind == "tone":
        sig = 0.5 * np.sin(2 * np.pi * freq * t)
    else:
        sig = np.zeros(n)
    frames = (np.stack([sig, sig], axis=1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(frames.tobytes())
    return path


srv = ThreadingHTTPServer(("127.0.0.1", PORT), appmod.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.3)

CTX = {}


@scenario("P1 tạo project trống -> list thấy + có project mặc định + storage")
def _():
    st, j = http_json("POST", "/api/projects", {"title": "Bài test P1"})
    assert st == 200 and j["project"]["id"], (st, j)
    CTX["p1"] = j["project"]["id"]
    st, j = http_json("GET", "/api/projects")
    assert st == 200, (st, j)
    ids = [x["id"] for x in j["items"]]
    assert "default" in ids and CTX["p1"] in ids, ids
    assert "projects_bytes" in j["storage"] and "total" in j["storage"]


@scenario("P2 mở project -> autosave lines/style/voice/ok -> mở lại còn nguyên")
def _():
    pid = CTX["p1"]
    st, j = http_json("POST", f"/api/projects/{pid}/open", {})
    assert st == 200 and j["project"]["id"] == pid, (st, j)
    lines = [
        {"text": "Câu một nam hát", "start": 0.5, "end": 2.0,
         "voice": "m", "ok": True},
        {"text": "Câu hai nữ hát", "start": 2.5, "end": 4.0,
         "voice": "f", "ok": False},
        {"text": "Câu ba giọng lạ", "start": 4.5, "end": 6.0,
         "voice": "x"},
    ]
    st, j = http_json("POST", "/api/project/current", {
        "title": "Bài test P1 (đã sửa)", "lines": lines,
        "style": {"color": "#FF5C8A", "size": 72},
        "bg": {"type": "gradient", "value": "hongtim"},
        "guide": 12, "lyrics_text": "Câu một nam hát\nCâu hai nữ hát"})
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/project/current")
    assert st == 200, (st, j)
    assert j["project"]["title"] == "Bài test P1 (đã sửa)", j["project"]
    got = j["lines"]
    assert len(got) == 3, got
    assert got[0]["voice"] == "m" and got[0]["ok"] is True, got[0]
    assert got[1]["voice"] == "f" and got[1]["ok"] is False, got[1]
    assert "voice" not in got[2], got[2]  # voice lạ bị sanitize loại
    st, j = http_json("POST", f"/api/projects/{pid}/open", {})
    assert st == 200 and len(j["lines"]) == 3, (st, j)
    assert abs(j["lines"][0]["start"] - 0.5) < 1e-6


@scenario("P3 project.json viết HỎNG tay -> list vẫn 200 + cờ corrupt, open/autosave 400")
def _():
    st, j = http_json("POST", "/api/projects", {"title": "Bài sẽ hỏng"})
    pid = j["project"]["id"]
    CTX["bad"] = pid
    st, j = http_json("POST", f"/api/projects/{pid}/open", {})
    assert st == 200, (st, j)
    pfile = os.path.join(appmod.PROJECTS_DIR, pid, "project.json")
    with open(pfile, "w", encoding="utf-8") as f:
        f.write("{ json hỏng {{{ không đóng ngoặc")
    st, j = http_json("GET", "/api/projects")
    assert st == 200, (st, j)
    item = next(x for x in j["items"] if x["id"] == pid)
    assert item["corrupt"] is True, item
    st, j = http_json("POST", f"/api/projects/{pid}/open", {})
    assert st == 400 and "error" in j, (st, j)
    # project đang mở chính là project hỏng -> autosave phải chặn 400
    st, j = http_json("POST", "/api/project/current", {"title": "x"})
    assert st == 400, (st, j)
    # dọn: xoá project hỏng (route xoá không đọc json) -> CURRENT về default
    st, j = http_json("POST", f"/api/projects/{pid}/delete", {})
    assert st == 200, (st, j)


@scenario("P4 xoá: default -> 400, id không có -> 404, id ký tự lạ -> 400, xoá thật -> mất khỏi list")
def _():
    st, j = http_json("POST", "/api/projects/default/delete", {})
    assert st == 400, (st, j)
    st, j = http_json("POST", "/api/projects/zzzzzzzzzz/delete", {})
    assert st == 404, (st, j)
    st, j = http_json("POST", "/api/projects/bad!id/delete", {})
    assert st == 400, (st, j)
    st, j = http_json("POST", "/api/projects/bad!id/open", {})
    assert st == 400, (st, j)
    st, j = http_json("POST", "/api/projects/zzzzzzzzzz/open", {})
    assert st == 404, (st, j)
    pid = CTX["p1"]
    st, j = http_json("POST", f"/api/projects/{pid}/delete", {})
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/projects")
    assert pid not in [x["id"] for x in j["items"]]


@scenario("P5 import-file WAV -> project có bài + duration; peaks qua HTTP đúng số bucket, max ~1")
def _():
    wav = write_wav(f"{TMP}/tone2s.wav", 2.0)
    with open(wav, "rb") as f:
        payload = f.read()
    st, j = http_json("POST", "/api/projects/import-file", payload,
                      {"X-File-Name": "tone2s.wav"})
    assert st == 200, (st, j)
    CTX["song_pid"] = j["project"]["id"]
    assert j["project"]["has_song"] is True, j["project"]
    assert abs(j["project"]["duration"] - 2.0) < 0.2, j["project"]
    pid = CTX["song_pid"]
    st, j = http_json("GET", f"/api/projects/{pid}/peaks?src=song&n=100")
    assert st == 200, (st, j)
    assert len(j["peaks"]) == 100, len(j["peaks"])
    assert max(j["peaks"]) > 0.99, max(j["peaks"])
    # project chưa có bài -> peaks 404
    st, j = http_json("POST", "/api/projects", {"title": "Chưa nhạc"})
    empty_pid = j["project"]["id"]
    st, j = http_json("GET", f"/api/projects/{empty_pid}/peaks?src=song")
    assert st == 404, (st, j)
    http_json("POST", f"/api/projects/{empty_pid}/delete", {})
    # import file giả danh nhạc -> 400 và thư mục project bị dọn
    st, j = http_json("POST", "/api/projects/import-file",
                      "chữ giả nhạc".encode("utf-8"),
                      {"X-File-Name": "gia.mp3"})
    assert st == 400, (st, j)


@scenario("P6 peaks hàm lõi: im lặng -> toàn 0 không sập; file rất ngắn -> vẫn ra peaks")
def _():
    silent = write_wav(f"{TMP}/silent2s.wav", 2.0, kind="silent")
    peaks = appmod._compute_peaks(silent, 100)
    assert peaks and all(p == 0.0 for p in peaks), peaks[:5]
    short = write_wav(f"{TMP}/short.wav", 0.05)
    peaks = appmod._compute_peaks(short, 1200)
    # 0.05s ở 22050Hz mono = ~1102 mẫu -> số bucket không vượt số mẫu
    assert 0 < len(peaks) <= 1103, len(peaks)
    assert max(peaks) > 0.99, max(peaks)


@scenario("P7 hàng đợi xuất: còn câu chưa căn -> 400; chưa có lời -> 400")
def _():
    pid = CTX["song_pid"]
    st, j = http_json("POST", f"/api/projects/{pid}/open", {})
    assert st == 200, (st, j)
    st, j = http_json("POST", "/api/export/queue",
                      {"project_id": pid, "config": {"format": "fb"}})
    assert st == 400, (st, j)  # chưa có lời
    st, j = http_json("POST", "/api/project/current", {
        "lines": [{"text": "Câu chưa căn", "start": None},
                  {"text": "Câu đã căn", "start": 0.5}]})
    assert st == 200, (st, j)
    st, j = http_json("POST", "/api/export/queue",
                      {"project_id": pid, "config": {"format": "fb"}})
    assert st == 400 and "chưa căn" in j["error"], (st, j)


@scenario("P8 hàng đợi xuất: render thật -> done + mp4 trong out_dir + .ass kèm + gỡ mục")
def _():
    pid = CTX["song_pid"]
    st, j = http_json("POST", "/api/project/current", {
        "lines": [{"text": "Câu một hát thử", "start": 0.2},
                  {"text": "Câu hai hát thử", "start": 1.1}]})
    assert st == 200, (st, j)
    out_dir = os.path.join(TMP, "out")
    st, j = http_json("POST", "/api/export/queue", {
        "project_id": pid,
        "config": {"format": "fb", "encoder": "cpu", "quality": "thap",
                   "burn": True, "export_ass": True,
                   "out_dir": out_dir, "filename": "bai test ky la"}})
    assert st == 200 and j["item"], (st, j)
    iid = j["item"]
    deadline = time.time() + 240
    item = None
    while time.time() < deadline:
        st, j = http_json("GET", "/api/export/queue")
        assert st == 200, (st, j)
        item = next((x for x in j["items"] if x["id"] == iid), None)
        if item and item["status"] in ("done", "error"):
            break
        time.sleep(1.0)
    assert item is not None and item["status"] == "done", item
    saved = item["saved_path"]
    assert saved and os.path.exists(saved), saved
    assert os.path.dirname(os.path.abspath(saved)) == \
        os.path.abspath(out_dir), saved
    assert os.path.getsize(saved) > 10_000, os.path.getsize(saved)
    assert item["size_bytes"] == os.path.getsize(saved)
    ass_side = os.path.splitext(saved)[0] + ".ass"
    assert os.path.exists(ass_side), ass_side
    st, j = http_json("POST", f"/api/export/queue/{iid}/remove", {})
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/export/queue")
    assert iid not in [x["id"] for x in j["items"]]


@scenario("P9 preset: lưu -> list thấy -> upsert không trùng -> xoá hết; thiếu tên -> 400")
def _():
    st, j = http_json("POST", "/api/presets", {"style": {}})
    assert st == 400, (st, j)
    body = {"name": "Mẫu test", "style": {"color": "#FF5C8A"},
            "bg": {"type": "gradient", "value": "demtim"},
            "export": {"format": "shorts", "quality": "vua"}}
    st, j = http_json("POST", "/api/presets", body)
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/presets")
    names = [x["name"] for x in j["items"]]
    assert names.count("Mẫu test") == 1, names
    body["style"] = {"color": "#00FF00"}
    st, j = http_json("POST", "/api/presets", body)
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/presets")
    mine = [x for x in j["items"] if x["name"] == "Mẫu test"]
    assert len(mine) == 1 and mine[0]["style"]["color"] == "#00FF00", mine
    st, j = http_json("POST", "/api/presets/delete", {"name": "Mẫu test"})
    assert st == 200, (st, j)
    st, j = http_json("GET", "/api/presets")
    assert "Mẫu test" not in [x["name"] for x in j["items"]]


@scenario("P10 cuối lưới: server vẫn khoẻ, trang chủ 200, app-info version 4.0.0")
def _():
    st, raw, _h = http("GET", "/")
    assert st == 200 and b"Karaoke" in raw, st
    st, j = http_json("GET", "/api/app-info")
    assert st == 200 and j["version"] == "4.0.0", (st, j)
    st, j = http_json("GET", "/api/export/info")
    assert st == 200 and "yt4k" in j["formats"], (st, j)


print()
fails = [r for r in RESULTS if not r[1]]
print(f"== TỔNG: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS, "
      f"{len(fails)} FAIL ==")
for name, ok, err in RESULTS:
    if not ok:
        print(f"  FAIL: {name} -> {err}")
sys.exit(1 if fails else 0)
