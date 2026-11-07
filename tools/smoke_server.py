"""Smoke test trọn vòng qua HTTP thật: nạp bài -> tách beat nhanh -> nạp .lrc
-> xuất MP4 -> kiểm file + trích khung hình kiểm chữ karaoke."""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod  # noqa: E402
from karaoke import media  # noqa: E402

PORT = 8771
BASE = f"http://127.0.0.1:{PORT}"


def req(method, path, body=None, headers=None, raw_json=False):
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers=headers or {})
    with urllib.request.urlopen(r, timeout=120) as resp:
        data = resp.read()
    return data if raw_json else json.loads(data.decode("utf-8"))


def wait_job(jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = req("GET", f"/api/job/{jid}")
        if job["status"] == "done":
            return job
        if job["status"] == "error":
            raise RuntimeError("JOB ERROR: " + str(job["error"]))
        time.sleep(0.4)
    raise TimeoutError(jid)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), appmod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    with open("/tmp/ktest/mix.wav", "rb") as f:
        payload = f.read()
    up = req("POST", "/api/upload-song", payload,
             {"X-File-Name": "bai-test.wav"})
    print("UPLOAD:", up)
    assert up["ok"] and abs(up["duration"] - 12.0) < 0.3

    sep = req("POST", "/api/separate", json.dumps({"mode": "fast"}).encode(),
              {"Content-Type": "application/json"})
    wait_job(sep["job"])
    print("SEPARATE(fast): done")

    lrc = ("[00:00.50]Câu một hát thử karaoke\n"
           "[00:04.50]Câu hai chữ chạy theo từng từ\n"
           "[00:08.50]Câu ba kiểm tra màu vàng\n")
    lines = req("POST", "/api/lrc", lrc.encode("utf-8"))
    print("LRC:", lines)
    assert len(lines["lines"]) == 3

    ren = req("POST", "/api/render", json.dumps({
        "lines": lines["lines"],
        "style": {"color": "#FFD400", "size": 64},
        "guide": 0,
        "bg": {"type": "color", "value": "#0b0e1a"},
        "audio": "inst",
    }).encode(), {"Content-Type": "application/json"})
    wait_job(ren["job"])
    print("RENDER: done")

    mp4 = os.path.join(appmod.WORK, "karaoke.mp4")
    assert os.path.exists(mp4) and os.path.getsize(mp4) > 100_000, mp4
    dur = media.probe_duration(mp4)
    print(f"MP4: {os.path.getsize(mp4)} bytes, {dur:.2f}s")
    assert abs(dur - 12.0) < 0.6

    frame = "/tmp/ktest/frame6.png"
    media.extract_frame(mp4, 6.0, frame)  # giữa câu 2: một phần chữ đã sang vàng
    print("FRAME:", frame)
    print("SMOKE PASS")


if __name__ == "__main__":
    main()
