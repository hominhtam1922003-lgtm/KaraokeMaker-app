"""Kiểm lỗi cho tính năng tự căn AI + lọc dòng rác (chạy: python tools/test_align.py).

Chỉ kiểm phần logic thuần (đối chiếu lời, nội suy, lọc dòng) bằng dữ liệu
nghe-giả — phần Whisper nghe thật kiểm ở mức tích hợp trên máy Windows.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from karaoke import align as alg  # noqa: E402
from karaoke import lyrics as lyr  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def heard_from(lines, start0=5.0, word_dur=0.32, line_gap=0.7, drop=(), extra=()):
    """Dựng bản nghe giả: các từ nối tiếp nhau, hết câu nghỉ line_gap giây."""
    words, t = [], start0
    for li, ln in enumerate(lines):
        if li > 0:
            t += line_gap
        for w in ln.split():
            if w in drop:
                continue
            words.append({"w": w, "start": round(t, 2),
                          "end": round(t + word_dur, 2)})
            t += word_dur
    for w, s in extra:
        words.append({"w": w, "start": s, "end": s + 0.3})
    words.sort(key=lambda x: x["start"])
    return words


LINES = [
    "Ngày thay đêm vội trôi giấc mơ êm đềm",
    "Tôi lênh đênh trên biển vắng",
    "Hoàng hôn chờ em chưa buông nắng",
    "Đừng tìm nhau vào hôm gió mưa tơi bời",
]

# 1) Khớp hoàn hảo
h = heard_from(LINES)
starts, ratio = alg.align_lines(h, LINES, duration=60.0)
check("perfect: ratio=1", ratio == 1.0, str(ratio))
check("perfect: first start = first word", abs(starts[0] - h[0]["start"]) < 0.01)
check("perfect: monotonic", all(b > a for a, b in zip(starts, starts[1:])),
      str(starts))
# start câu 2 phải đúng mốc từ đầu câu 2 trong bản nghe
w2 = next(w for w in h if w["w"] == "Tôi")
check("perfect: line2 start exact", abs(starts[1] - w2["start"]) < 0.01,
      f"{starts[1]} vs {w2['start']}")

# 2) Bản nghe thiếu vài từ + thừa tiếng nói đầu bài
h2 = heard_from(LINES, drop=("vội", "chưa"), extra=[("xin", 0.5), ("chào", 0.9)])
starts2, ratio2 = alg.align_lines(h2, LINES, duration=60.0)
check("missing/extra words: ratio cao", ratio2 >= 0.85, str(ratio2))
check("missing/extra words: đủ 4 mốc tăng dần",
      len(starts2) == 4 and all(b > a for a, b in zip(starts2, starts2[1:])),
      str(starts2))

# 3) Lời dán KHÔNG dấu -> lượt bỏ dấu phải cứu được
plain = [alg.strip_diacritics(x) for x in LINES]
starts3, ratio3 = alg.align_lines(h, plain, duration=60.0)
check("no-diacritics lyrics: ratio >= 0.9", ratio3 >= 0.9, str(ratio3))
check("no-diacritics lyrics: start câu 1 đúng",
      abs(starts3[0] - starts[0]) < 0.6, f"{starts3[0]} vs {starts[0]}")

# 4) Một câu giữa không hề được hát (nhạc dạo) -> nội suy giữa hai câu kề
lines4 = LINES[:2] + ["Câu này là nhạc dạo không ai hát"] + LINES[2:]
starts4, _ = alg.align_lines(h, lines4, duration=60.0)
check("interlude line interpolated between neighbours",
      starts4[1] < starts4[2] < starts4[3], str(starts4))

# 5) Câu đầu/cuối không khớp -> ngoại suy an toàn, kẹp theo duration
lines5 = ["Mở đầu nói chuyện phiếm"] + LINES + ["Kết thúc cảm ơn mọi người"]
starts5, _ = alg.align_lines(h, lines5, duration=60.0)
check("leading/trailing unmatched handled",
      starts5[0] >= 0 and starts5[-1] > starts5[-2], str(starts5))
check("duration clamp", all(s <= 59.7 for s in starts5), str(starts5))

# 6) Các lỗi phải ném rõ ràng
for name, fn in [
    ("empty heard raises", lambda: alg.align_lines([], LINES)),
    ("unrelated lyrics raises",
     lambda: alg.align_lines(h, ["Hoàn toàn khác hẳn không liên quan gì hết"])),
    ("blank lyrics raises", lambda: alg.align_lines(h, ["   ", ""])),
]:
    try:
        fn()
        check(name, False)
    except ValueError:
        check(name, True)

# 7) Lọc dòng rác — đúng các dòng trong ảnh user gửi + không ăn mất câu thật
junk = ["--:--Lyrics:", "--:--Verse 1:", "--:--Chorus:", "--:--Verse 2:",
        "--------------------", "[Chorus]", "(Điệp khúc)", "Verse 2:", ""]
real = ["Gọi tôi thức giấc cơn ngủ mê", "Dìu tôi đi lúc quên lối về",
        "Quãng đời mai sau luôn cạnh nhau", "Anh nói: ngày mai mình cưới nhau"]
got = lyr.parse_plain("\n".join(junk + real))
check("junk lines removed, real kept", got == real, str(got))
check("clean_line keeps colon lyric",
      lyr.clean_line("Anh nói: ngày mai") == "Anh nói: ngày mai")
check("clean_line strips --:-- from real line",
      lyr.clean_line("--:--Ngày thay đêm") == "Ngày thay đêm")

# 8) align_full: giờ từng từ đơn điệu, nằm trong khoảng câu, đủ số từ
full = alg.align_full(h, LINES, duration=60.0)
check("align_full: starts khớp align_lines", full["starts"] == starts)
ok_words = True
for li, row in enumerate(full["words"]):
    if len(row) != len(LINES[li].split()):
        ok_words = False
    last = full["starts"][li]
    for s, e in row:
        if s < last - 0.06 or e <= s:
            ok_words = False
        last = s
check("align_full: word times monotonic & valid", ok_words, str(full["words"][:1]))

# 9) segments_to_lines: cắt đoạn dài, bỏ đoạn [âm nhạc], gộp đuôi ngắn
def seg(text, words, t0):
    ws, t = [], t0
    for w in words:
        ws.append({"w": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
        t += 0.32
    return {"text": text, "start": t0, "end": t, "words": ws}

long_words = ("Một hai ba bốn năm sáu, bảy tám chín mười "
              "mười một mười hai mười ba mười bốn").split()
segs = [
    seg("[âm nhạc]", ["[âm", "nhạc]"], 0.0),
    seg("Một hai ba bốn năm sáu, bảy tám chín mười mười một mười hai mười ba mười bốn",
        long_words, 3.0),
    seg("Câu ngắn thôi", ["Câu", "ngắn", "thôi"], 12.0),
]
lines9 = alg.segments_to_lines(segs)
check("segments: bracket segment dropped", all("âm" not in l["text"] for l in lines9),
      str([l["text"] for l in lines9]))
check("segments: long segment split into >=2 lines", len(lines9) >= 3,
      str(len(lines9)))
check("segments: each line <= 13 words",
      all(len(l["words"]) <= 13 for l in lines9),
      str([len(l["words"]) for l in lines9]))
check("segments: words carry times & text joins",
      lines9[0]["words"][0][0] == 3.0 and lines9[0]["start"] == 3.0)
check("segments: sorted by start",
      [l["start"] for l in lines9] == sorted(l["start"] for l in lines9))

print()
print("FAILED:", FAILS if FAILS else "none")
sys.exit(1 if FAILS else 0)
