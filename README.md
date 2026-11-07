# Karaoke Maker

App PC làm video karaoke: tách beat bằng AI (UVR-MDX-NET), căn nhịp lời theo từng câu, chữ chạy theo từng từ, xuất MP4 1080p.

## Cách dùng (bản .exe)

**Cách nhanh nhất — tự động toàn phần:** mở `KaraokeMaker.exe` → nạp file bài hát → bấm **⚡ Làm video karaoke tự động**. App tự tách beat, tự nghe & chép lời (Whisper), tự căn nhịp theo từng từ, tự xuất video. Xong!

**Cách thủ công (kiểm soát từng bước):**

1. Nạp file bài hát (nhạc hoặc video).
2. Tách beat: chế độ **AI** (sạch, chậm hơn) hoặc **Nhanh** (cắt giọng stereo).
3. Dán lời (mỗi dòng một câu) hoặc nạp file `.lrc` có sẵn mốc giờ. Dán lời từ web nhạc vào, app tự bỏ các dòng nhãn mục kiểu `--:--Verse:`, `[Chorus]`.
4. Nếu chưa có `.lrc`: bấm **Tự căn bằng AI** để app gắn mốc giờ (lần đầu dùng tải model ~470 MB), hoặc căn tay bằng nút/Space.
5. Chọn **mẫu chữ** (10 mẫu có sẵn) hoặc tự chỉnh màu/font/cỡ chữ, hiệu ứng chữ chạy (quét mượt / nhảy từng từ), hiện câu kế tiếp, thẻ tên bài mở đầu; chọn nền (5 mẫu gradient / đen / ảnh / video), giọng dẫn 0–40% rồi xuất MP4.

Mọi xử lý chạy local trên máy, không cần internet (trừ lần tải app).

## Phát triển

- `app.py` — máy chủ web local (Python stdlib) + API.
- `karaoke/` — `lyrics.py` (LRC + ASS \k + lọc dòng rác), `media.py` (FFmpeg), `mdx.py` (tách beat ONNX), `align.py` (tự căn nhịp: faster-whisper + đối chiếu lời).
- `web/` — giao diện.
- Đóng gói: PyInstaller (`KaraokeMaker.spec`); CI Windows tự tải FFmpeg + model rồi build `.exe` và phát hành ở Releases.
