"""Lưới kiểm lỗi đa kịch bản cho Karaoke Maker (lệnh user 2026-11-06):
input hỏng/rỗng/sai định dạng/sai mã hoá, giá trị biên, bấm trùng tác vụ,
đường dẫn ký tự lạ, file giả danh. Mỗi kịch bản PASS/FAIL rõ ràng.

Chạy: .venv/bin/python tools/test_errors.py
"""
import io
import json
import os
import subprocess
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

from karaoke import lyrics as lyr  # noqa: E402
from karaoke import media, mdx  # noqa: E402
import app as appmod  # noqa: E402

TMP = "/tmp/kerr"
os.makedirs(TMP, exist_ok=True)
RESULTS = []
SECTION = (sys.argv[1] if len(sys.argv) > 1 else "ALL").upper()
ONLY = os.environ.get("ERR_ONLY", "")


def scenario(name):
    def deco(fn):
        if SECTION != "ALL" and not name.startswith(SECTION):
            return fn
        if ONLY and ONLY not in name:
            return fn
        try:
            fn()
            RESULTS.append((name, True, ""))
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"FAIL  {name} -> {type(e).__name__}: {e}")
        return fn
    return deco


def write_wav(path, seconds=1.0, sr=44100, ch=2, kind="tone", freq=440.0):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    if kind == "tone":
        sig = 0.5 * np.sin(2 * np.pi * freq * t)
    elif kind == "silent":
        sig = np.zeros(n)
    elif kind == "noise":
        sig = np.random.default_rng(1).uniform(-1, 1, n)
    else:
        raise ValueError(kind)
    if ch == 1:
        frames = (sig * 32767).astype(np.int16)
    else:
        frames = np.stack([sig, sig], axis=1).astype(np.int16) \
            if kind != "noise" else \
            (np.stack([sig, sig], axis=1) * 32767).astype(np.int16)
        if kind == "tone":
            frames = (np.stack([sig, sig], axis=1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(frames.tobytes())
    return path


def ffmpeg(*args):
    cmd = [media.ffmpeg_bin(), "-y", "-v", "error", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])


# ---------------- fixtures ----------------
TINY = write_wav(f"{TMP}/tiny.wav", 0.3)
SILENT = write_wav(f"{TMP}/silent.wav", 2.0, kind="silent")
MONO = write_wav(f"{TMP}/mono.wav", 1.0, ch=1)
LOW_SR = write_wav(f"{TMP}/lowsr.wav", 1.0, sr=22050)
NOISE = write_wav(f"{TMP}/noise.wav", 1.0, kind="noise")
TEXTFILE = f"{TMP}/fake.wav"
with open(TEXTFILE, "w") as f:
    f.write("đây không phải file nhạc, chỉ là chữ")
NOAUDIO_MP4 = f"{TMP}/noaudio.mp4"
ffmpeg("-f", "lavfi", "-i", "color=c=red:s=320x240:r=10:d=1",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", NOAUDIO_MP4)
ODD_PNG = f"{TMP}/odd.png"
ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=333x777", "-frames:v", "1", ODD_PNG)
FAKE_PNG = f"{TMP}/fake.png"
with open(FAKE_PNG, "w") as f:
    f.write("PNG giả danh bằng chữ")

FF = media.ffmpeg_bin()


# ---------------- LYRICS ----------------
@scenario("L1 parse_lrc lộn xộn: BOM, CRLF, metadata, offset, đa tag, dòng rác")
def _():
    text = ("﻿[ti:Bài test]\r\n[ar:Ca sĩ]\r\n[offset:250]\r\n"
            "dòng không tag\n[00:01.00]Câu một\n"
            "[00:02.00][00:05.50]Câu lặp hai lần\n"
            "[99:99.99]Câu giờ quái\n[00:03.00]\n[00:04.000]Câu bốn\n")
    lines = lyr.parse_lrc(text)
    starts = [round(l["start"], 2) for l in lines]
    assert 1.25 in starts, f"offset +250ms chưa được áp: {starts}"
    assert starts.count(2.25) == 1 and starts.count(5.75) == 1, starts
    assert all(l["text"] for l in lines), "có câu rỗng lọt qua"
    assert starts == sorted(starts)


@scenario("L2 parse_lrc rác thuần -> []")
def _():
    assert lyr.parse_lrc("không có gì\n[xx:yy]sai\n") == []
    assert lyr.parse_lrc("") == []


@scenario("L4 build_ass ký tự đặc biệt: {} \\ emoji < > không phá cấu trúc ASS")
def _():
    import re as _re
    ass = lyr.build_ass([{"start": 0.0, "end": 4.0,
                          "text": r"Chữ {lạ} \ đường 🎤 <ok> 100%"}],
                        {"color": "#FFD400"})
    body = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    body = _re.sub(r"\{[^}]*\}", "", body)  # gỡ mọi thẻ override ASS hợp lệ (\k, \kf, \fad...)
    assert "{" not in body and "}" not in body, body
    assert "\\" not in body.split(",,", 1)[-1], body


@scenario("L5 build_ass opts hỏng: size chữ lạ, màu sai -> dùng mặc định, không sập")
def _():
    import re as _re
    ass = lyr.build_ass([{"start": 0, "end": 2, "text": "A B"}],
                        {"color": "red", "size": "abc"})
    m = _re.search(r"Style: Kara,Arial,64,(&H[0-9A-F]+),", ass)
    assert m and _re.fullmatch(r"&H00[0-9A-F]{6}", m.group(1)), ass[:400]


@scenario("L6 assign_ends lời chưa sắp xếp + giờ âm -> tự xếp, end > start")
def _():
    out = lyr.assign_ends([{"start": 5, "text": "b"}, {"start": -2, "text": "a"},
                           {"start": 9, "text": "c"}], 12.0)
    assert [o["text"] for o in out] == ["a", "b", "c"], out
    assert all(o["end"] > o["start"] for o in out), out
    assert out[0]["start"] == 0.0


@scenario("L7 assign_ends câu nằm ngoài độ dài bài -> cửa sổ không âm")
def _():
    out = lyr.assign_ends([{"start": 1, "text": "x"}, {"start": 20, "text": "y"}], 12.0)
    assert all(o["end"] > o["start"] for o in out), out
    lyr.build_ass(out)  # không sập


@scenario("L9 hai câu trùng giờ bắt đầu -> ASS vẫn end > start")
def _():
    out = lyr.assign_ends([{"start": 2, "text": "một"}, {"start": 2, "text": "hai"}], 8.0)
    ass = lyr.build_ass(out)
    assert ass.count("Dialogue:") == 2


# ---------------- MEDIA ----------------
@scenario("M1 probe_duration file không tồn tại / file hỏng -> 0.0, không văng")
def _():
    assert media.probe_duration("/tmp/kerr/khong-co.wav") == 0.0
    assert media.probe_duration(TEXTFILE) == 0.0


@scenario("M2 extract_audio file chữ / không tồn tại -> RuntimeError rõ ràng")
def _():
    for bad in (TEXTFILE, "/tmp/kerr/khong-co.mp3"):
        try:
            media.extract_audio(bad, f"{TMP}/x.wav")
            raise AssertionError(f"không báo lỗi cho {bad}")
        except RuntimeError:
            pass


@scenario("M3 extract_audio video không có tiếng -> RuntimeError")
def _():
    try:
        media.extract_audio(NOAUDIO_MP4, f"{TMP}/x.wav")
        raise AssertionError("video câm mà không báo lỗi")
    except RuntimeError:
        pass


@scenario("M4 center_cut với duration=0/None -> không chia cho 0")
def _():
    media.center_cut("/tmp/ktest/mix.wav", f"{TMP}/cc0.wav", lambda p, l="": None, 0)
    media.center_cut("/tmp/ktest/mix.wav", f"{TMP}/ccn.wav", None, None)
    assert os.path.getsize(f"{TMP}/cc0.wav") > 1000


@scenario("M5 mix_with_guide biên 0 / 40 / 999 / âm -> kẹp 0-40, không sập")
def _():
    for g in (0, 40, 999, -5):
        media.mix_with_guide("/tmp/ktest/mix.wav", "/tmp/ktest/mix.wav", g,
                             f"{TMP}/mix{g}.wav")
        assert os.path.getsize(f"{TMP}/mix{g}.wav") > 1000


@scenario("M6 render: đường dẫn ASS có dấu cách + nháy đơn + dấu hai chấm")
def _():
    weird = "/tmp/k test's: dir"
    os.makedirs(weird, exist_ok=True)
    ass_path = os.path.join(weird, "lyrics.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(lyr.build_ass([{"start": 0.2, "end": 2.5, "text": "Kiểm đường dẫn lạ"}]))
    out = f"{TMP}/weird.mp4"
    media.render_video({"type": "color", "value": "#0b0e1a"},
                       "/tmp/ktest/mix.wav", ass_path, out, 3.0)
    assert os.path.getsize(out) > 10_000


@scenario("M7 render: màu nền rác -> RuntimeError (không treo)")
def _():
    ass_path = f"{TMP}/a.ass"
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(lyr.build_ass([{"start": 0, "end": 2, "text": "A"}]))
    try:
        media.render_video({"type": "color", "value": "0xZZZZ"},
                           "/tmp/ktest/mix.wav", ass_path, f"{TMP}/bad.mp4", 2.0)
        raise AssertionError("màu rác mà render thành công")
    except RuntimeError:
        pass


@scenario("M8 render: ảnh nền là file chữ giả danh -> RuntimeError")
def _():
    ass_path = f"{TMP}/a.ass"
    try:
        media.render_video({"type": "image", "value": FAKE_PNG},
                           "/tmp/ktest/mix.wav", ass_path, f"{TMP}/bad2.mp4", 2.0)
        raise AssertionError("ảnh giả mà render thành công")
    except RuntimeError:
        pass


@scenario("M9 render: ảnh nền kích thước lẻ 333x777 -> ra đúng 1920x1080")
def _():
    ass_path = f"{TMP}/a.ass"
    out = f"{TMP}/odd.mp4"
    media.render_video({"type": "image", "value": ODD_PNG},
                       "/tmp/ktest/mix.wav", ass_path, out, 2.0)
    r = subprocess.run([media.ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "json", out],
                       capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    assert (st["width"], st["height"]) == (1920, 1080), st


@scenario("M10 render video cực ngắn 0.4s")
def _():
    ass_path = f"{TMP}/a.ass"
    out = f"{TMP}/tiny.mp4"
    media.render_video({"type": "color", "value": "#0b0e1a"},
                       "/tmp/ktest/mix.wav", ass_path, out, 0.4)
    assert abs(media.probe_duration(out) - 0.4) < 0.25


# ---------------- MDX ----------------
@scenario("X1 model không tồn tại -> FileNotFoundError có thông điệp")
def _():
    try:
        mdx.separate_mdx(TINY, f"{TMP}/o.wav", model_path="/tmp/kerr/no.onnx")
        raise AssertionError("thiếu model mà không báo")
    except FileNotFoundError as e:
        assert "model" in str(e).lower()


@scenario("X2 tách AI file cực ngắn 0.3s -> xong, độ dài khớp")
def _():
    out = f"{TMP}/tiny_inst.wav"
    mdx.separate_mdx(TINY, out)
    assert abs(media.probe_duration(out) - 0.3) < 0.15


@scenario("X3 tách AI file im lặng tuyệt đối -> không chia cho 0, ra im lặng")
def _():
    out = f"{TMP}/sil_inst.wav"
    mdx.separate_mdx(SILENT, out)
    data = mdx.load_wav_f32(out)
    assert float(np.abs(data).max()) < 0.02


@scenario("X4 tách AI file mono -> tự nhân đôi kênh, chạy xong")
def _():
    out = f"{TMP}/mono_inst.wav"
    mdx.separate_mdx(MONO, out)
    assert media.probe_duration(out) > 0.8


@scenario("X5 WAV sai tần số mẫu 22050 -> ValueError rõ ràng")
def _():
    try:
        mdx.load_wav_f32(LOW_SR)
        raise AssertionError("sai SR mà không báo")
    except ValueError:
        pass


@scenario("X6 file chữ đội lốt WAV -> phải văng lỗi")
def _():
    try:
        mdx.load_wav_f32(TEXTFILE)
        raise AssertionError("file chữ mà đọc được")
    except Exception:
        pass


@scenario("X7 tách AI nhiễu full-scale (đỉnh 1.0) -> xong, đỉnh ra <= 1.0")
def _():
    out = f"{TMP}/noise_inst.wav"
    mdx.separate_mdx(NOISE, out)
    data = mdx.load_wav_f32(out)
    assert float(np.abs(data).max()) <= 1.0


# ---------------- HTTP ----------------
PORT = 8772
BASE = f"http://127.0.0.1:{PORT}"


def http(method, path, body=None, headers=None):
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def http_json(method, path, body=None, headers=None):
    st, raw, _ = http(method, path, body, headers)
    try:
        return st, json.loads(raw.decode("utf-8"))
    except Exception:
        return st, {}


def wait_job(jid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, job = http_json("GET", f"/api/job/{jid}")
        if job.get("status") == "done":
            return job
        if job.get("status") == "error":
            raise RuntimeError("JOB ERROR: " + str(job.get("error")))
        time.sleep(0.5)
    raise TimeoutError(jid)


if SECTION in ("ALL", "H"):
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), appmod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)


@scenario("H1 tách beat khi chưa có bài -> 400")
def _():
    st, j = http_json("POST", "/api/separate", json.dumps({"mode": "fast"}).encode(),
                      {"Content-Type": "application/json"})
    assert st == 400, (st, j)


@scenario("H3 render với câu chưa có giờ (start=null) -> 400, không phải 500")
def _():
    st, j = http_json("POST", "/api/render", json.dumps({
        "lines": [{"start": None, "text": "Chưa căn"}]}).encode(),
        {"Content-Type": "application/json"})
    assert st == 400, (st, j)


@scenario("H5 nạp .lrc rác -> 400")
def _():
    st, j = http_json("POST", "/api/lrc", "toàn chữ không mốc giờ".encode())
    assert st == 400, (st, j)


@scenario("H6 nạp .lrc mã hoá UTF-16 (BOM) -> đọc được")
def _():
    lrc = "[00:01.00]Câu một\r\n[00:03.00]Câu hai\r\n"
    st, j = http_json("POST", "/api/lrc", lrc.encode("utf-16"))
    assert st == 200 and len(j.get("lines", [])) == 2, (st, j)


@scenario("H7 tải lên file nhạc 0 byte -> 400")
def _():
    st, j = http_json("POST", "/api/upload-song", b"", {"X-File-Name": "rong.mp3"})
    assert st == 400, (st, j)


@scenario("H8 tải lên file nhạc hỏng -> JSON lỗi, server vẫn sống")
def _():
    st, j = http_json("POST", "/api/upload-song",
                      "không phải nhạc".encode(), {"X-File-Name": "hong.mp3"})
    assert st in (400, 500) and "error" in j, (st, j)
    st2, _, _ = http("GET", "/")
    assert st2 == 200


@scenario("H9 hỏi job không tồn tại -> 404")
def _():
    st, _j = http_json("GET", "/api/job/deadbeef99")
    assert st == 404, st


@scenario("H13 tải ảnh nền giả danh (file chữ) -> 400")
def _():
    st, j = http_json("POST", "/api/upload-bg-image",
                      "chữ giả ảnh".encode(), {"X-File-Name": "gia.png"})
    assert st == 400, (st, j)


@scenario("H2/H10/H12 nạp bài thật -> Range đuôi đúng -> render, bấm render lần 2 bị chặn 409")
def _():
    with open("/tmp/ktest/song.wav", "rb") as f:
        payload = f.read()
    st, j = http_json("POST", "/api/upload-song", payload,
                      {"X-File-Name": "bai-that.wav"})
    assert st == 200 and abs(j["duration"] - 45.0) < 1.0, (st, j)
    # Range đuôi: bytes=-100 phải trả 100 byte cuối của file ĐANG PHỤC VỤ
    # (file làm việc đã trích lại, kích thước khác file gốc một chút)
    st, raw, hdr = http("GET", "/api/audio/song", headers={"Range": "bytes=-100"})
    assert st == 206 and len(raw) == 100, (st, len(raw))
    total = int(hdr.get("Content-Range", "/0").split("/")[-1])
    assert hdr["Content-Range"].startswith(f"bytes {total-100}-"), hdr
    # Range rác -> trả nguyên file 200
    st, raw, _ = http("GET", "/api/audio/song", headers={"Range": "bytes=abc-def"})
    assert st == 200, st
    # Render + bấm trùng
    body = json.dumps({
        "lines": [{"start": 1.0, "text": "Câu một"}, {"start": 8.0, "text": "Câu hai"},
                  {"start": 20.0, "text": "Câu ba"}],
        "style": {"color": "#FFD400", "size": 64}, "guide": 0,
        "bg": {"type": "color", "value": "#0b0e1a"}, "audio": "orig"}).encode()
    st, j = http_json("POST", "/api/render", body, {"Content-Type": "application/json"})
    assert st == 200 and "job" in j, (st, j)
    st2, j2 = http_json("POST", "/api/render", body, {"Content-Type": "application/json"})
    assert st2 == 409, (st2, j2)
    wait_job(j["job"])
    st, raw, _ = http("GET", "/api/video")
    assert st == 200 and len(raw) > 100_000


@scenario("H14 cuối lưới: server vẫn khoẻ, trang chủ 200")
def _():
    st, _, _ = http("GET", "/")
    assert st == 200


print()
fails = [r for r in RESULTS if not r[1]]
print(f"== TỔNG: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS, {len(fails)} FAIL ==")
for name, ok, err in RESULTS:
    if not ok:
        print(f"  FAIL: {name} -> {err}")
sys.exit(1 if fails else 0)
