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


---

# Đợt vá 07/11/2026 (Quan Hiểu Đồng) — nền xem trước · "thành công giả" · chuỗi lời

Bối cảnh: 3 bằng chứng máy thật trên bản exe giao diện 3 bước (v3.0.0; pipeline
xử lý là cùng dòng mã với v4 — xem header web/app.js): (1) chip "Nền: video
của bạn" nhưng xem trước tối trơn; (2) xuất "xong" mà video chỉ có gradient
tím + nhạc, không chữ, không phải nền đã chọn; (3) video có chữ ở nửa sau —
nửa đầu không lời, lời sai be bét ("Okey don't idols").

## Nguyên nhân gốc (đã chứng minh bằng code + số đo)

1. **Xem trước**: `pvRender()` với nền ảnh/video chỉ tô màu `#232a45` + gắn
   nhãn — không hề nạp file; server không có route phát file nền. Lỗi CHỈ ở
   xem trước trên đường chuẩn (xuất qua `media.render_video` có
   `-stream_loop -1` dùng đúng file, đã tái hiện: nền đỏ → khung đỏ thật).
2. **Xuất mất nền**: hai lỗi thầm — (a) upload nền lần 2 khác đuôi không dọn
   file cũ, `_project_ctx` nhặt `sorted(glob)[0]` = file CŨ (tái hiện: xuất
   vẫn ra nền đỏ sau khi đã đổi sang webm xanh); (b) `resolve_bg()` rơi
   LẶNG về nền màu khi thiếu file — project lưu `bg type=video` mà không có
   file vẫn báo "done" (tái hiện: khung ≈ #0b0e1a). Video của user ra
   gradient tím (demtim) = cùng họ rơi-lặng-về-mặc-định ở tầng project/lưu
   cấu hình trên bản v3.
3. **Xuất mất chữ**: không một cổng kiểm nào tồn tại — ASS 0 sự kiện
   Dialogue, lines chưa căn giờ, hay đốt chữ hỏng đều đi thẳng tới "done".
4. **Chép lời sai**: `whisper_worker.py` và đường dự phòng
   `align._transcribe_inprocess` gọi `model.transcribe(...)` KHÔNG truyền
   `language` → Whisper tự nhận diện ngôn ngữ từ 30s đầu, `_info` bị vứt bỏ
   không kiểm. ĐO THẬT (xem mục Kiểm): trên bài hát tiếng Việt, nhận diện
   ra **tiếng Anh (en, prob 0,79)** → giải mã cả bài như tiếng Anh.
5. **Mất nửa đầu**: pipeline không có cổng phủ lời nào; chép sai ngôn ngữ
   làm độ phủ sụp (34% so với 51% khi khoá tiếng Việt trên cùng dữ liệu)
   và các đoạn đầu bị bộ lọc rác loại — không gì chặn việc xuất tiếp.

## Đã sửa

- **Xem trước nền thật** (`app.py`, `web/index.html`, `web/app.js`,
  `web/style.css`): route mới `GET /api/bg-preview?kind=video|image` phát
  ĐÚNG file mà khâu xuất dùng (một nguồn sự thật — STATE đi theo project
  đang mở); codec lạ (HEVC/VP9-in-MP4/MPEG-4...) được chuyển mã bản xem
  trước H.264 `bg_preview.mp4` cạnh file gốc (cache theo mtime:size; file
  gốc giữ nguyên cho xuất); nền WebView2 không đọc được/thiếu file → hiện
  thông báo rõ trong khung xem trước, không im lặng tối trơn. `pvRender`
  gắn `<video>`/`<img>` thật làm lớp nền (blur chỉ áp lên media, đồng bộ
  play/seek theo audio), lỗi tải → `pvBgFailed` phân biệt 404 (chưa có
  file) với lỗi định dạng.
- **Xuất dùng đúng nền**: upload dọn mọi file nền cũ cùng loại (kể cả khác
  đuôi) + xoá cache xem trước; `_project_ctx` chọn file nền theo mtime mới
  nhất; `_require_bg_resolved()` — yêu cầu nền image/video mà resolve ra
  khác loại → lỗi rõ "Chưa tìm thấy file nền..." — gắn ở hàng đợi xuất,
  `/api/render`, `/api/auto-all`, job auto-link, cả 2 nhánh resolve của
  batch (batch còn lại đi qua `run_pipeline` như cũ).
- **Cổng chữ hai lớp — áp MỌI đường xuất có đốt chữ**: (i) tiền xuất
  `_require_ass_events()` — ASS sắp đốt có 0 Dialogue → chặn trước render;
  (ii) sau xuất `verify_export_text()` — trích khung ở 45% + 75% của câu
  đầu/giữa/cuối từ chính MP4 vừa xuất, đếm pixel màu chữ của style (đã
  hát/chưa hát/song ca) hoặc gần trắng ở nửa dưới khung; ngưỡng
  `max(30px, 0,08% dải)` — hiệu chuẩn từ ca thật H2 (câu ngắn 3 chữ trên
  khung 1080p chỉ cho 98–115px ở khung mẫu; video trơn trên nền phẳng
  ~0px). Không đạt → job lỗi "Video xuất ra KHÔNG thấy chữ karaoke...",
  hàng đợi còn xoá file hỏng khỏi thư mục lưu của user. Gắn ở
  `run_pipeline` (phủ cả auto-all/auto-link/batch), `_run_export_item`,
  job `/api/render`. `burn=False` bỏ qua theo thiết kế (user chủ động
  không đốt chữ).
- **Chuỗi lời**: khoá `language="vi"` ở worker + đường dự phòng (mồi tiếng
  Việt giữ nguyên — mồi không khoá được ngôn ngữ, chỉ là phụ trợ). Cổng
  phủ lời `_check_lyric_lines()` trong `run_pipeline` (nhánh tự chép):
  mốc giờ ngoài thời lượng bài → chặn; câu đầu bắt đầu sau 25% bài MÀ
  stem giọng đo RMS ≥ 0,015 trong 25% đầu (có hát thật) → chặn với thông
  điệp chỉ đường chuẩn. `/api/auto-align` ưu tiên nghe mốc từng từ trên
  stem giọng nếu đã tách.
- **Luồng lời theo lệnh chốt của user (07/11)**: đường CHÍNH là dán lời +
  AI căn giờ. Panel lời trong Studio mở sẵn; hướng dẫn 1 dòng "Đường
  chuẩn: dán lời → Dùng lời này → Tự căn nhịp bằng AI"; nút Tự căn là nút
  chính (grad, lớn); hàng đợi "Làm trọn gói" bắt buộc đã có lời dán; nút
  AI tự chép tách riêng, ghi nhãn **"Bản nháp tự chép — nghe hát hay sai
  chữ, chỉ dùng khi không có lời"**; pipeline trả `warning` khi dùng lời
  tự chép và `pollJob` nổi cảnh báo ngay khi job xong; `lineStats` hiện
  "⚠ N câu CHƯA KHỚP — nghe thử & sửa trước khi xuất" màu cảnh báo (chip
  ⚠ Chưa khớp từng câu đã có từ v4, nay có tổng đếm nổi bật).

## Kiểm — số đo thật

- **Thử Whisper trên bài hát thật** ("Duyên Phận", bản Thái Thịnh —
  YouTube chặn IP VM bằng 429/bot-check nên lấy từ SoundCloud; 150 giây
  đầu, BẢN PHỐI, model small int8): 
  - Hành vi CŨ (không khoá ngôn ngữ): `info.language=en, prob=0,79` —
  23 câu, phủ 34%, **tỉ lệ câu có dấu tiếng Việt = 0,00**; đầu ra toàn
  tiếng Anh bịa: "The day I'm lazy when I'm speaking", "You're my star",
  "What do u call me?" — đúng chữ ký lỗi user chụp.
  - Khoá `language="vi"` (gọi trực tiếp): 24 câu, phủ 51%, tỉ lệ VI 0,96.
  - Qua worker của app (code sau sửa): 20 câu, phủ 44%, tỉ lệ VI 1,00.
  - Chất lượng vùng hát khi khoá: tiếng Việt đọc được nhưng còn sai câu
  chữ (model small + beam 1 + hát) — đúng bản chất BẢN NHÁP; kèm hiện
  tượng bịa 3 dòng trên đoạn nhạc dạo (hệ quả `vad_filter=False` theo
  thiết kế). Đây là lý do đường dán lời là đường sản xuất.
  - Lượt đo trên STEM GIỌNG: MDX tách xong (có file vocal 150s) nhưng
  file stem bị một tiến trình ngoài trên VM dùng chung xoá mất trước khi
  đo (không rõ nguồn; đã kiểm không phải code app) — ô stem-vs-phối chưa
  đo lại được trong đợt này; cổng phủ lời đã kiểm bằng stem tổng hợp có
  kiểm soát (P16).
- **Lưới test**: `test_projects.py` **16/16** (thêm P11–P16: preview phát
  đúng file + xuất đúng nền đỏ; đổi đuôi webm → 1 file + preview + xuất
  xanh kể cả nền 0,6s ngắn hơn bài; xoá file nền → hàng đợi ERROR rõ;
  file giả danh → 400, codec MPEG-4 → preview chuyển mã H.264 còn gốc
  nguyên; cổng chữ nhận video có chữ/chặn video trơn; cổng lời 3 ca) ·
  `test_errors.py` **34/34** · `test_auto`, `test_ass2`, `test_align`,
  `test_batch`, `test_link`: FAILED none · `test_whisper` 14/14 ·
  `smoke_server.py` SMOKE PASS · `node --check web/app.js` +
  `py_compile`: OK. (Ca H2 của test_errors từng bị cổng chữ chặn oan —
  câu ngắn 98–115px dưới ngưỡng đầu 194px; đã hiệu chuẩn lại ngưỡng như
  ghi ở trên và H2 qua 34/34.)
- **Xuất thử có trích khung**: P11 (nền đỏ: mean R thắng tuyệt đối), P12
  (nền lime webm ở giây 1,6 — nền ngắn đã lặp đúng), P15 (video có chữ
  qua cổng, video trơn bị cổng chặn), repro H2 (khung 480px: vàng 33px +
  trắng ~80px/câu ngắn).

## Phát hiện phụ + việc gác lại (đợt sau)

- Tải model Whisper lần đầu qua huggingface_hub 2.4.0 (đường xet) có lúc
  văng `open() got an unexpected keyword argument 'metadata_errors'` —
  thử lại thì tải xong và model chạy bình thường. `requirements.txt`
  KHÔNG ghim phiên bản (`faster-whisper>=1.0`) nên bản exe đóng gói theo
  thư viện mới nhất tại thời điểm build — đề xuất đợt sau: ghim phiên
  bản + dịch thông điệp lỗi tải model sang tiếng Việt rõ ràng.
- Hàng đợi xuất của project có trường hợp chưa qua cổng nền: cấu hình
  `burn=False` (chủ động không đốt chữ) — theo thiết kế, không phải lỗi.
- Cổng pixel là lưới thứ hai sau cổng đếm sự kiện ASS: trên nền video
  rất sáng/bận rộn, pixel gần-trắng của chính nền có thể làm cổng dễ qua
  — chấp nhận ở mức lưới bắt thảm hoạ "đốt mà không ra chữ"; kiểm bằng
  mắt khi nghiệm thu vẫn là chốt cuối.

---

# Đợt nâng cấp BATCH LƯU BỀN (sau v4.1.0 — Quan Hiểu Đồng; VERSION giữ nguyên 4.1.0, Tổng 98 chốt số bản khi phát hành)

## Thiết kế

### 1) batch.json — trạng thái batch ghi xuống đĩa
- File `work/batch.json` (cùng cấp thư mục `work/batch/` chứa thư mục từng
  bài): `{"version": 1, "saved_at", "items": [...]}`. Mỗi bài ghi: `id`,
  `kind` (link/file), `url` hoặc `src` (file staged), `title`, `status`
  (pending/running/done/error — trạng thái runtime "queued" ghi thành
  "pending"), `progress`, `label`, `error`, `project_id`, `opts` đã dùng
  (want_video/sep_mode/style/guide/bg), `cleaned` (danh sách file đã dọn),
  `created_at`/`updated_at`/`finished_at`.
- Ghi NGUYÊN TỬ: ghi `batch.json.tmp` rồi `os.replace`. `_save_batch()`
  được gọi ở MỌI chuyển trạng thái: tạo bài (cả 2 endpoint), worker nhận
  bài (running), có tiêu đề thật từ YouTube, xong (done — sau dọn đĩa),
  lỗi (error). Lỗi ghi file chỉ in log, không làm hỏng tác vụ đang chạy.

### 2) Khôi phục + Chạy tiếp
- `main()` gọi `_load_batch()` trước khi mở server. Bài done → hiện lại
  done, ctx nối lại `karaoke.mp4` trên đĩa + beat trỏ sang project (Xem/
  Tải/Lưu/tải beat chạy như chưa từng tắt app). Bài error → giữ nguyên
  kèm lỗi. Bài pending/running lúc tắt → "queued" chờ; riêng bài từng
  "running" gắn cờ `interrupted` + nhãn "Bị gián đoạn (app đã tắt giữa
  chừng)". Bài khôi phục KHÔNG tự chạy khi mở app.
- Endpoint mới `POST /api/batch/resume`: chỉ xếp lại bài status "queued"
  chưa xong — bài done không chạy lại, bài error giữ nguyên để chẩn
  đoán. Chặn xếp trùng bằng tập `_BATCH_INFLIGHT` (bấm Chạy tiếp 2 lần:
  lần 2 trả resumed=0).
- Giao diện: mở app tự gọi `checkRestoredBatch()` — có đợt lưu bền thì
  hiện lại danh sách + nút "▶ Chạy tiếp N bài dở" (chỉ hiện khi có bài
  queued chưa live). Bài khôi phục hiện badge "⏸ Chờ chạy tiếp". Trường
  API mới: `interrupted`, `live`, `sep_mode` trong `_batch_public`;
  pollBatch chỉ coi bài queued-CÒN-LIVE là đang hoạt động (bài chờ chạy
  tiếp không giữ poll chạy mãi).
- Bài file chạy tiếp: file staged gốc đã bị xoá sau lần nạp đầu thì
  chạy tiếp từ `song.wav` đã trích trong thư mục bài (so đường dẫn
  tuyệt đối để không tự trích đè lên chính nó); mất cả hai → lỗi rõ
  "File nguồn của bài này đã mất — hãy thêm lại file".

### 3) Song song theo chế độ tách (thay queue.Queue bằng bộ xếp lịch)
- Hằng số: `BATCH_AI_PARALLEL = 1`, `BATCH_PARALLEL = 2` (= số worker).
  Worker lấy bài qua `_batch_take()`: quét hàng chờ, chỉ lấy bài mà chế
  độ tách của nó còn "suất" (ai < 1, fast < 2). Batch toàn AI → 1
  bài/lần; batch toàn fast → 2 bài/lần.
- Batch LẪN hai chế độ: tính theo TỪNG BÀI — bài ai chiếm suất ai (tối
  đa 1), bài fast chiếm suất fast (tối đa 2), tổng đồng thời không quá
  số worker (2). Bài chưa có suất nằm chờ tại chỗ; bài phía sau thuộc
  chế độ còn suất được lấy trước (không kẹt đầu hàng). Lỗi từng bài vẫn
  độc lập như cũ; trần 20 link/đợt giữ nguyên.

### 4) Dọn đĩa khi done
- Chỉ chạy trong `_cleanup_batch_item()` sau khi bài đạt done THẬT
  (run_pipeline đã qua cổng `verify_export_text` mới tới được đây) và
  SAU khi project đã được tạo (project giữ bản sao riêng). Bài lỗi
  không bao giờ dọn.
- Danh sách file bị xoá trong thư mục bài: `song.wav`, `inst.wav`,
  `vocal.wav`, `mixed.wav` (WAV toàn bài), `yt_src.*` (nguồn yt-dlp
  tải về), `*.pcm16k` (WAV 16kHz trung gian của khâu nghe/căn lời —
  gồm cả `vocal.wav.pcm16k` ở đường tự chép), `grad_*.png` /
  `gradanim_*.mp4` (nền gradient app tự sinh trong thư mục bài, sinh
  lại được từ opts).
- GIỮ: `karaoke.mp4` (video ra), `lyrics.ass` + mọi `*.lrc` kèm theo,
  và toàn bộ thư mục project. Sau dọn, ctx của bài trỏ `inst_wav` sang
  bản beat trong project để nút "tải beat" của bài vẫn chạy; danh sách
  file đã dọn ghi vào trường `cleaned` trong batch.json.

### 5) batch.json hỏng
- Parse lỗi / sai cấu trúc → in 1 dòng cảnh báo (stderr), đổi tên file
  thành `batch.json.corrupt` (giữ nguyên để xem lại), coi như batch
  trống, app mở bình thường. Từng mục trong file mà sai lệch quá (thiếu
  id, link trống) thì bỏ qua mục đó, không kéo sập cả đợt.

## Lỗi bắt được nhờ lưới khi làm đợt này
- **Đua trạng thái ở POST /api/batch (có từ trước, đợt này làm lộ rõ):**
  endpoint cũ kiểm tra "còn bài queued nào không" bằng cách đọc lại
  status SAU vòng tạo — worker nhanh tay chuyển bài sang "running"
  trước khi kiểm tra thì đợt toàn link tốt bị trả 400 oan. Đợt này thêm
  `_save_batch()` (ghi đĩa) vào giữa càng nới rộng cửa sổ đua → test bắt
  được ngay. Đã sửa: ghi nhận `had_valid` ngay tại thời điểm tạo bài.

## Kiểm — số đo thật (chạy trên VM, stub yt-dlp + Whisper như lưới cũ)
- **test_batch MỞ RỘNG: 41/41 PASS** — gồm các ca mới:
  cổng song song (unit, monkeypatch `_run_batch_item` ghi độ song song
  thật: ai tối đa 1, tổng tối đa 2, 6/6 bài done) · ghi/đọc batch.json
  đủ trường + opts · tắt app giữa batch (stub tải chậm 10s, kill server
  khi có done + có dở) → mở lại: done giữ done, bài dở thành chờ +
  `interrupted`, video bài done xem lại được · Chạy tiếp: xếp đúng số
  bài dở, bấm lần 2 resumed=0, bài done cũ KHÔNG chạy lại (mtime
  karaoke.mp4 nguyên vẹn), bài lỗi bị resume bỏ qua + file chẩn đoán
  (sentinel) còn nguyên · dọn đĩa cả ở phase thường và phase chạy tiếp
  (chỉ còn karaoke.mp4 + lyrics.ass) · batch.json rác → app vẫn chạy,
  batch trống, có batch.json.corrupt.
- **Toàn bộ lưới cũ, KHÔNG hồi quy:** test_projects 16/16 ·
  test_errors 34/34 · test_whisper FAILED none · test_ass2 FAILED
  none · test_align FAILED none · test_auto FAILED none · test_link
  FAILED none · smoke_server SMOKE PASS.
- Hai việc bảo trì test kèm theo (không thuộc code app): kỳ vọng version
  trong test_projects P10 cập nhật 4.0.0 → 4.1.0 cho khớp bản đã phát
  hành (VERSION trong app.py KHÔNG đổi); fixture `/tmp/ktest/song.wav`
  bị mất theo /tmp như các lần trước — đã tạo lại dạng sóng tổng hợp
  45s đúng chuẩn test_errors đòi (duration 45±1s).

## Điểm chưa chắc chắn
- Lượt đo "tắt app" trong test là kill tiến trình server (SIGTERM) —
  tương đương app bị đóng đột ngột ở mức tiến trình; ca mất điện/rút
  phích giữa lúc ghi batch.json chưa mô phỏng được, nhưng ghi nguyên tử
  tmp+rename là cơ chế chuẩn cho ca đó (file hoặc cũ hoặc mới, không
  rách nửa chừng).
- Trần song song khi batch lẫn chế độ mới kiểm ở mức unit (đếm độ song
  song qua `_run_batch_item` giả lập) — pipeline thật (MDX + Whisper +
  render) chạy lẫn ai/fast đồng thời chưa đo trên máy thật; giới hạn
  tổng = số worker (2) giữ tải không vượt quá mức v4 vẫn chạy.
