"""Kiểm các tính năng ASS v2 (quét mượt, 2 dòng, thẻ tên bài, giờ từng từ)
và nền gradient. Chạy: python tools/test_ass2.py"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from karaoke import lyrics as lyr  # noqa: E402
from karaoke import media  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


LINES = [
    {"start": 2.0, "end": 5.6, "text": "Ngày thay đêm vội trôi",
     "words": [(2.0, 2.3), (2.32, 2.6), (2.62, 2.95), (2.97, 3.3), (3.32, 3.7)]},
    {"start": 6.2, "end": 9.0, "text": "Tôi lênh đênh trên biển vắng"},
    {"start": 10.0, "end": 13.0, "text": "Hoàng hôn chờ em chưa buông nắng"},
]

# 1) Mặc định quét mượt \kf + fade + không có KaraNext khi chưa bật 2 dòng
ass = lyr.build_ass(LINES, {})
check("sweep: has \\kf tags", "\\kf" in ass)
check("sweep: fade in main events", "{\\fad(120,180)}" in ass)
check("two_line off: no KaraNext", "KaraNext" not in ass)
check("no title: no KaraTitle", "KaraTitle" not in ass)

# 2) pop: nhảy từng từ, không \kf
ass2 = lyr.build_ass(LINES, {"effect": "pop", "fade": False})
check("pop: no \\kf", "\\kf" not in ass2)
check("pop: has \\k", "\\k" in ass2)
check("fade off: no \\fad", "\\fad" not in ass2)

# 3) two_line: style KaraNext + đúng lines-1 sự kiện xem trước
ass3 = lyr.build_ass(LINES, {"two_line": True})
check("two_line: KaraNext style", "Style: KaraNext" in ass3)
check("two_line: preview events = lines-1",
      ass3.count(",KaraNext,") == len(LINES) - 1, str(ass3.count(",KaraNext,")))

# 4) title: thẻ tên bài ở 0.00, kết thúc trước câu đầu (câu đầu ở 2.0 -> end 2.0)
ass4 = lyr.build_ass(LINES, {"title": "Phép Màu (Test)"})
check("title: KaraTitle style", "Style: KaraTitle" in ass4)
m = re.search(r"Dialogue: 2,0:00:00\.00,([0-9:.]+),KaraTitle.*Phép Màu", ass4)
check("title: event 0->2.00 with text", bool(m) and m.group(1) == "0:00:02.00",
      ass4.splitlines()[-6] if not m else "")

# 5) giờ từng từ: tổng thời lượng các thẻ của câu 1 khớp độ dài câu (±2cs)
ev1 = next(l for l in ass.splitlines() if ",Kara," in l and "Ngày" in l)
durs = [int(x) for x in re.findall(r"\\kf?(\d+)", ev1)]
total = int(round((5.6 - 2.0) * 100))
check("word times: tag durations sum to line length",
      abs(sum(durs) - total) <= 2, f"sum={sum(durs)} total={total}")

# 6) khoảng lặng đầu câu: từ đầu bắt đầu muộn 0.8s -> thẻ lặng {\k80}
late = [{"start": 2.0, "end": 5.0, "text": "Một hai ba",
         "words": [(2.8, 3.1), (3.2, 3.5), (3.6, 4.0)]}]
ass6 = lyr.build_ass(late, {})
check("lead-in silence tag {\\k80}", "{\\k80}" in ass6, ass6.splitlines()[-1])

# 7) assign_ends: giữ words + tôn trọng end có sẵn hợp lệ + kẹp end quá đà
inp = [
    {"start": 6.2, "end": 9.0, "text": "B hai", "words": [(6.2, 6.5)]},
    {"start": 2.0, "end": 5.0, "text": "A một", "words": [(2.0, 2.3)]},
    {"start": 10.0, "end": 99.0, "text": "C ba"},
]
out = lyr.assign_ends(inp, 12.0)
check("assign_ends: sorted", [x["text"] for x in out] == ["A một", "B hai", "C ba"])
check("assign_ends: provided end kept", out[0]["end"] == 5.0, str(out[0]))
check("assign_ends: words preserved", out[0].get("words") == [(2.0, 2.3)])
check("assign_ends: oversized end clamped to duration",
      out[2]["end"] <= 12.0, str(out[2]))

# 8) nền gradient: đủ 5 mẫu, ra ảnh 1920x1080 đọc được; kind lạ không sập
import subprocess  # noqa: E402
for kind in media.GRADIENTS:
    p = f"/tmp/grad_{kind}.png"
    media.make_gradient_bg(kind, p)
    r = subprocess.run([media.ffprobe_bin(), "-v", "error", "-select_streams",
                        "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", p],
                       capture_output=True, text=True, timeout=30)
    check(f"gradient {kind}: 1920x1080", r.stdout.strip() == "1920,1080",
          r.stdout + r.stderr)
media.make_gradient_bg("khong-co-kind-nay", "/tmp/grad_x.png")
check("gradient: unknown kind falls back", os.path.exists("/tmp/grad_x.png"))

# 9) v3: zoom / type / countdown / duet / PlayRes dọc
dlg = lambda a: [x for x in a.splitlines()  # noqa: E731
                 if x.startswith("Dialogue:") and ",Kara," in x]
azz = lyr.build_ass(LINES, {"effect": "zoom"})
z0 = dlg(azz)[0]
check("zoom: has scale pulse tags", "\\fscx120" in z0 and "\\t(" in z0,
      z0[:160])
check("zoom: no \\kf", "\\kf" not in z0)
aty = lyr.build_ass(LINES, {"effect": "type"})
t0 = dlg(aty)[0]
n_chars = sum(len(w) for w in "Ngày thay đêm vội trôi".split())
check("type: one \\k tag per char",
      t0.count("{\\k") == n_chars, f'{t0.count("{{\\k")} vs {n_chars}')

GAP = [{"start": 1.0, "end": 3.0, "text": "Câu một hát trước"},
       {"start": 8.0, "end": 10.0, "text": "Câu hai cách xa"}]
acd = lyr.build_ass(GAP, {"countdown": True})
dots = [x for x in acd.splitlines() if ",Dots," in x]
check("countdown: 3 dot events before far line", len(dots) == 3, str(len(dots)))
check("countdown: first dot at start-1.5s",
      bool(dots) and "0:00:06.50" in dots[0], dots[0][:70] if dots else "")
check("countdown off: no Dots", ",Dots," not in lyr.build_ass(GAP, {}))

adu = lyr.build_ass(LINES, {"duet_color": "#00E5FF"})
dl = dlg(adu)
check("duet: odd line gets \\1c duet color",
      len(dl) >= 2 and "\\1c&H00FFE500" in dl[1],
      dl[1][:120] if len(dl) > 1 else "")
check("duet: even lines untouched",
      "\\1c" not in dl[0] and (len(dl) < 3 or "\\1c" not in dl[2]))

avr = lyr.build_ass(LINES, {"play_x": 1080, "play_y": 1920})
check("playres: vertical 1080x1920",
      "PlayResX: 1080" in avr and "PlayResY: 1920" in avr)

# 10) v3: lọc dòng rác kênh (is_junk_line)
check("junk: subscribe CTA", lyr.is_junk_line(
    "Hãy subscribe cho kênh Ghiền Mì Gõ để không bỏ lỡ những video hay"))
check("junk: cam on da xem", lyr.is_junk_line("Cảm ơn các bạn đã đón xem"))
check("junk: dang ky kenh", lyr.is_junk_line("Nhớ đăng ký kênh để ủng hộ mình"))
check("junk: real lyric kept", not lyr.is_junk_line(
    "Cảm ơn đời mỗi sớm mai thức dậy"))
check("junk: real lyric kept 2", not lyr.is_junk_line(
    "Ngày mai em đi, biển nhớ tên em gọi về"))

print()
print("FAILED:", FAILS if FAILS else "none")
sys.exit(1 if FAILS else 0)
