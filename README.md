# Karaoke Maker

App PC làm video karaoke: tách beat bằng AI (UVR-MDX-NET), căn nhịp lời theo từng câu, chữ chạy theo từng từ, xuất MP4 1080p.

## Cách dùng (bản .exe)

1. Mở `KaraokeMaker.exe` — trình duyệt tự bật giao diện.
2. Nạp file bài hát (nhạc hoặc video).
3. Tách beat: chế độ **AI** (sạch, chậm hơn) hoặc **Nhanh** (cắt giọng stereo).
4. Dán lời (mỗi dòng một câu) hoặc nạp file `.lrc` có sẵn mốc giờ.
5. Nếu chưa có `.lrc`: căn nhịp bằng cách bấm nút/Space đúng lúc mỗi câu bắt đầu.
6. Chọn màu chữ, cỡ chữ, nền (đen / ảnh / video), giọng dẫn 0–40% rồi xuất MP4.

Mọi xử lý chạy local trên máy, không cần internet (trừ lần tải app).

## Phát triển

- `app.py` — máy chủ web local (Python stdlib) + API.
- `karaoke/` — `lyrics.py` (LRC + ASS \k), `media.py` (FFmpeg), `mdx.py` (tách beat ONNX).
- `web/` — giao diện.
- Đóng gói: PyInstaller (`KaraokeMaker.spec`); CI Windows tự tải FFmpeg + model rồi build `.exe` và phát hành ở Releases.
