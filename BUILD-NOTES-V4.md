# Karaoke Maker v4.0.0 — Ghi chú bản dựng

**Nguyên tắc (lệnh user 07/11/2026):** lấy KHUNG THIẾT KẾ "KaraStudio"
(ngôn ngữ thị giác + cấu trúc Thư viện → Studio → Xuất) nhưng TÍNH NĂNG
GIỮ 100% CỦA MÌNH. Tool làm video karaoke để đăng YouTube/TikTok —
**TUYỆT ĐỐI KHÔNG có màn Hát / chấm điểm giọng hát trực tiếp** (ảnh 3
của khung chỉ dùng để biết phần nào phải bỏ).

## Đã làm theo khung

### Ngôn ngữ thị giác (cả 4 view dùng chung)
- Nền tối sâu `#07070d`, thẻ `#12121d` bo góc lớn, gradient chủ đạo
  hồng `#ff4d7e` → tím `#8b5cf6` (nút chính, thanh tiến trình, sóng âm,
  thumbnail dự án), chip trạng thái màu (xanh = xong, cam = đang chờ,
  xám = chưa làm).
- Bố cục app có sidebar trái cố định (logo, điều hướng, hộp dung lượng)
  giống khung Thư viện; Studio 3 cột giống khung Studio; Xuất có lưới
  thẻ preset định dạng giống khung Xuất.

### 1) THƯ VIỆN (view mặc định khi mở app)
- **Tầng DỰ ÁN mới (lưu bền):** mỗi bài = 1 project trong
  `work/projects/<id>/project.json` (tiêu đề, nguồn, file làm việc,
  dòng lời + mốc giờ, style, trạng thái beat/lời/đã xuất, thời gian sửa
  cuối). Project `default` chính là thư mục phiên làm việc cũ của v3 —
  toàn bộ endpoint v3 chạy trên project đang mở, không vỡ luồng cũ.
- Thẻ dự án gần đây (thumbnail gradient theo tên bài + chip trạng thái:
  Đã tách beat / Chưa tách beat · Đã căn lời / Bản nháp lời / Chưa có
  lời · Đã xuất video) + bảng "Bài hát" đầy đủ để tìm nhanh.
- Tìm kiếm theo tiêu đề/tên file; hộp Dung lượng dự án (đã dùng / ổ đĩa).
- Nhập nhạc: nhiều file một lượt (mỗi file thành 1 project), tạo project
  trống, nhập bằng link YouTube (chạy trọn pipeline thành project),
  xoá project (project mặc định không xoá được).
- Panel "Tạo video karaoke" giữ nguyên 2 đường của v3: dán nhiều link
  (hàng đợi hàng loạt, xong tự thành project trong Thư viện) và chọn
  file + chọn cách tách (AI MDX / cắt nhanh).
- project.json hỏng: Thư viện vẫn mở bình thường, thẻ project gắn cờ
  "File dự án hỏng", mở project đó báo lỗi rõ — không nuốt lặng.

### 2) STUDIO
- Danh sách dòng lời kèm mốc giờ bắt đầu–kết thúc từng câu, nút chỉnh
  ±0,1s, bấm đúp sửa chữ tại chỗ (sửa đổi số từ thì tự bỏ mốc từng từ),
  dòng AI căn chưa khớp trực tiếp gắn chip **⚠ Chưa khớp** (từ trường
  `line_ok` mới của `align_full`: câu có ≥1 từ khớp trực tiếp = đã khớp,
  câu toàn nội suy = chưa khớp).
- **WAVEFORM:** server tính peaks từ file nhạc (ffmpeg giải mã mono
  22.050Hz → biên độ cực đại từng bucket, chuẩn hoá 0..1, cache theo
  mtime+size), vẽ canvas: phần đã phát tô gradient hồng→tím, **mốc đoạn
  D1..Dn** ở đầu mỗi đoạn (đoạn mới khi quãng nghỉ giữa 2 câu ≥ 3s,
  đoạn đang phát màu hồng, đoạn khác màu xanh), bấm vào sóng để tua.
- Gắn nhịp tay giữ nguyên semantics v3: nút Phát & gắn nhịp, phím
  **Space** ở đầu mỗi dòng, chip báo chế độ gắn nhịp BẬT/TẮT, Hoàn tác /
  Làm lại từ đầu; phím ↑/↓ đổi dòng đang chọn; transport ⏮ ▶/⏸ ⏭,
  tua ±5s, đồng hồ thời gian.
- Panel phải theo khung: mẫu phong cách nhanh, font, cỡ chữ, bảng màu
  "đã hát" và "chưa hát" (swatch bấm chọn), hiệu ứng quét màu / nhảy
  từng từ (pop) / phóng to (zoom) / hiện từng chữ (type), hiện 2 dòng,
  mờ mở/đóng câu, chấm đếm ngược, thanh tiến trình.
- **Song ca có gán giọng TỪNG DÒNG (mới, làm thật ở tầng ASS):** bật
  Song ca → mỗi dòng có chip giọng bấm xoay vòng Nữ / Nam / chưa gán,
  hoặc chọn dòng rồi bấm nút "Nữ · hồng" / "Nam · xanh" / bỏ gán ở
  panel. ASS builder (`karaoke/lyrics.py`): dòng gán `voice: "f"/"m"`
  được tô `duet_female_color` / `duet_male_color` (thiếu thì lùi về
  `duet_color`); màu trùng màu hát chính thì không gắn thẻ thừa; dòng
  chưa gán GIỮ luật cũ của v3 (câu lẻ dùng `duet_color`). `assign_ends`
  giữ thêm trường `voice` + `ok`. Xem trước trong Studio cũng tô câu kế
  theo giọng đã gán.
- Nền: gradient (5 mẫu) / gradient động / màu phẳng / ảnh / video của
  user + **làm mờ nền** (`bg_blur` truyền xuống ffmpeg `gblur` cho nền
  ảnh/video; gradient chỉ mờ ở xem trước). Tỉ lệ 16:9 / 9:16 / 1:1.
- **Tự lưu (autosave):** mọi thay đổi (lời, mốc, giọng, style, nền,
  guide) được lưu vào project.json sau 600ms, nhãn "Đã lưu tự động ✓"
  ở thanh trên giống khung.
- Giữ đủ công cụ v3 trong Studio: dán lời (tự lọc dòng tiêu đề/rác),
  nạp .lrc, AI căn nhịp (Whisper tiến trình con), tách beat (AI/nhanh)
  ngay trên project, tải beat riêng, làm tự động trọn gói 1 nút.

### 3) XUẤT VIDEO
- 4 preset định dạng theo khung: **YouTube 16:9 (1920×1080) · Shorts /
  TikTok 9:16 (1080×1920) · Facebook 1:1 (1080×1080) · YouTube 4K
  (3840×2160)**.
- Bộ mã hoá: Tự động / NVENC / CPU. Server **đo thật** khả năng NVENC
  bằng cách mã hoá thử 15 khung (không chỉ liệt kê encoder) + hiện tên
  GPU (nvidia-smi) làm badge; chọn NVENC mà render sập thì tự lùi CPU.
- Chất lượng theo bitrate (Cao 16 Mbps / Vừa 10 Mbps / Thấp 6 Mbps),
  ước tính dung lượng + thời gian xuất theo preset/encoder đã chọn.
- Đốt lời vào video bật/tắt (`ass_path=None` = xuất video không chữ),
  tuỳ chọn xuất kèm file `.ass` đặt cạnh MP4.
- Thư mục lưu + tên file tuỳ chỉnh (trùng tên tự thêm " (2)", " (3)"…);
  mặc định thư mục Videos\KaraokeMaker như v3.
- **HÀNG ĐỢI XUẤT:** 1 worker chạy lần lượt từng bài, tiến độ % từng
  bài + nhãn bước render + encoder thật đã dùng; bài render từ dữ liệu
  project ĐÃ LƯU (không cần đang mở); validate trước khi nhận: chưa có
  bài / chưa có lời / còn câu chưa căn → báo lỗi rõ, không nhận; gỡ
  được mục chưa chạy (đang chạy → 409). Số bài đang chờ hiện badge ở
  menu trái.
- **"Lưu cấu hình làm mẫu":** lưu preset gồm style + nền + cấu hình
  xuất dưới tên tự đặt (upsert theo tên), áp lại từ màn Xuất.
- Sau khi xuất xong: bản sao `karaoke.mp4` được chép về thư mục project
  + project gắn trạng thái Đã xuất video.

### 4) CÀI ĐẶT
- Hiện phiên bản 4.0.0, thư mục lưu video, dung lượng dự án, cách tách
  beat mặc định (đồng bộ với cả 3 cụm radio trong app), nút mở thư mục
  video đã lưu.

## Điểm của khung KHÔNG làm / làm khác — kèm lý do
- **Màn Hát + chấm điểm giọng (ảnh 3): BỎ HẲN theo lệnh user.** Tool
  này làm video để đăng, không hát trực tiếp, không chấm điểm.
- **Logo kênh + Intro kênh trong panel Nền: để khoá (disabled) kèm ghi
  chú.** Pipeline hiện chưa có quản lý tư liệu kênh (file logo/intro
  dùng chung mọi project); bật công tắc mà không có dữ liệu thật là
  nút giả — vi phạm luật nối dây của nhà. Để dành khi có mục quản lý
  tư liệu kênh riêng.
- **Ước tính dung lượng/thời gian ở màn Xuất là ƯỚC TÍNH** từ bitrate
  đã chọn và hệ số tốc độ đo tham khảo (NVENC ~0,35×, CPU ~0,95× thời
  lượng, 4K ×2,2) — ghi rõ dấu "~", không phải số đo từng lần xuất.
- Thumbnail project dùng gradient theo tên bài (khung dùng ảnh bìa
  thật) vì pipeline chưa trích khung hình bìa từ video nguồn.

## Nâng cấp kỹ thuật kèm theo
- `karaoke/media.py`: `has_nvenc()` mã hoá thử thật + cache,
  `gpu_name()`, `render_video` thêm encoder/bitrate/blur/không-đốt-chữ,
  timeout tỉ lệ theo diện tích khung (4K), trả về encoder thật đã dùng.
  Mặc định giữ nguyên hành vi v3 (libx264 CRF 20).
- `karaoke/align.py`: `align_full` trả thêm `line_ok` từng câu.
- Cửa sổ app 1360×900, tiêu đề "Karaoke Maker 4.0.0".
- `KaraokeMaker.spec` KHÔNG đổi (cấu trúc `web/` giữ nguyên).

## Kết quả kiểm lỗi (lưới đa kịch bản) — chạy 07/11/2026, TẤT CẢ ĐẠT
- `node --check web/app.js` + `py_compile app.py karaoke/*.py`: OK.
- **Mới — `tools/test_projects.py`: 10/10 PASS.** Tạo/mở/lưu/xoá project
  + autosave giữ voice/ok; project.json viết hỏng tay (list vẫn 200 +
  cờ corrupt, open + autosave đều 400 rõ ràng); xoá default → 400, id
  không có → 404, id ký tự lạ (`bad!id`) → 400; import-file WAV + file
  giả danh; peaks qua HTTP (đúng 100 bucket, max ≈ 1) + hàm lõi (file
  im lặng → toàn 0 không sập, file 0,05s → vẫn ra peaks không vượt số
  mẫu); hàng đợi xuất: chưa lời/chưa căn hết → 400, render thật (1:1,
  CPU) → done + MP4 đúng thư mục đích + `.ass` kèm + gỡ mục; preset
  lưu/upsert/xoá + thiếu tên → 400.
- **Mở rộng — `tools/test_ass2.py` mục 11 (song ca từng dòng): PASS.**
  Dòng Nam lấy màu Nam riêng; màu Nữ trùng màu chính → không thẻ thừa;
  dòng chưa gán giữ luật cũ (lẻ = duet_color, chẵn = không thẻ); không
  cấu hình song ca → voice bị bỏ qua hẳn; `assign_ends` giữ voice/ok,
  loại voice lạ.
- **Lưới cũ giữ nguyên: `test_errors.py` 34/34 PASS** (đúng baseline
  v3; lưu ý H2 cần fixture `/tmp/ktest/song.wav` 45s — file này không
  test nào tự tạo, đã tạo lại bản tổng hợp 45s để chạy), `test_align`,
  `test_auto`, `test_link`, `test_whisper` (gồm ca AI sập cứng — server
  vẫn sống), `test_batch`: **FAILED: none**; `test_mdx`: chạy trọn (đo
  chất lượng tách như cũ); **`smoke_server.py`: SMOKE PASS**.
- `tools/test_song.py` là script BENCHMARK cần file bài thật — không
  chạy (như các đợt trước).

## Việc còn lại cho Tổng 98
- Bump workflow lên tag v4.0.0 + push từ chat trực tiếp (bản này KHÔNG
  đụng `.github/workflows` theo lệnh phân công).
- Chạy Cổng Chạy Thử trên APK/exe thật trước phán quyết GO như luật nhà.
