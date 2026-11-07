"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  duration: 0, instReady: false, lines: [], tapped: false,
  tapIndex: 0, tapping: false, color: "#FFD400", baseColor: "#FFFFFF",
  outlineW: 3, gradKind: "demtim", ratio: "16:9",
};
const tapAudio = new Audio();
tapAudio.preload = "auto";

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.style.borderColor = isErr ? "var(--err)" : "var(--ok)";
  t.hidden = false;
  clearTimeout(toast._h);
  toast._h = setTimeout(() => (t.hidden = true), 4200);
}
function fmt(s) {
  if (!isFinite(s)) return "0:00";
  s = Math.max(0, Math.round(s));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function bust(url) { return url + "?v=" + Date.now(); }
function sepMode() {
  return document.querySelector('input[name="sepmode"]:checked').value;
}
function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function postRaw(url, body, headers) {
  const r = await fetch(url, { method: "POST", body, headers });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Lỗi " + r.status));
  return data;
}
async function postJSON(url, obj) {
  return postRaw(url, JSON.stringify(obj), { "Content-Type": "application/json" });
}
function pollJob(jobId, progressEl, onDone, onErr) {
  const bar = progressEl.querySelector(".bar");
  const pct = progressEl.querySelector(".pct");
  progressEl.hidden = false;
  progressEl.classList.remove("err");
  bar.style.width = "0%"; pct.textContent = "0%";
  let fails = 0;
  const iv = setInterval(async () => {
    try {
      const r = await fetch("/api/job/" + jobId);
      const job = await r.json();
      fails = 0;
      bar.style.width = job.progress + "%";
      pct.textContent = (job.label ? job.label + " · " : "") + job.progress + "%";
      if (job.status === "done") { clearInterval(iv); onDone && onDone(job.result); }
      else if (job.status === "error") {
        // Lỗi phải HIỆN RÕ và NẰM LẠI trên màn hình — toast thoáng qua làm
        // người dùng tưởng app "im luôn" không rõ chuyện gì.
        clearInterval(iv);
        progressEl.classList.add("err");
        bar.style.width = "100%";
        pct.textContent = "✗ " + (job.error || "Lỗi không rõ");
        (onErr || ((e) => toast(e, true)))(job.error || "Lỗi không rõ");
      }
    } catch (e) {
      // Không nuốt lặng vô hạn: mất kết nối nhiều nhịp liên tiếp = app
      // nhiều khả năng đã tắt — nói thẳng để người dùng mở lại app.
      fails++;
      if (fails >= 8) {
        clearInterval(iv);
        progressEl.classList.add("err");
        bar.style.width = "100%";
        pct.textContent = "✗ Mất kết nối với app — app có thể đã bị tắt. "
          + "Mở lại file KaraokeMaker.exe rồi làm lại bước này.";
        (onErr || ((e2) => toast(e2, true)))("Mất kết nối với app");
      }
    }
  }, 400);
}

/* ---------- Tab Link / File ---------- */
function showTab(link) {
  $("paneLink").hidden = !link;
  $("paneFile").hidden = link;
  $("tabLink").classList.toggle("active", link);
  $("tabFile").classList.toggle("active", !link);
}
$("tabLink").addEventListener("click", () => showTab(true));
$("tabFile").addEventListener("click", () => showTab(false));

/* ---------- Bài hát từ file ---------- */
$("songFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  $("songDropText").textContent = "Đang nạp: " + file.name + " ...";
  try {
    const data = await postRaw("/api/upload-song", file,
      { "X-File-Name": encodeURIComponent(file.name) });
    state.duration = data.duration;
    $("songName").textContent = data.name;
    $("songDur").textContent = fmt(data.duration);
    $("songInfo").hidden = false;
    $("songPlayer").src = bust("/api/audio/song");
    $("songDropText").textContent = "Đã nạp: " + file.name + " (bấm để đổi bài)";
    state.instReady = false;
    $("instInfo").hidden = true;
    $("btnAutoAll").disabled = false;
    toast("Đã nạp bài hát. Bấm nút làm video tự động, hoặc xuống bước 2 xử lý lời trước.");
  } catch (err) {
    $("songDropText").textContent = "Bấm để chọn 1 file nhạc / video";
    toast(err.message, true);
  }
});

/* ---------- Tách beat riêng ---------- */
$("btnSeparate").addEventListener("click", async () => {
  if (!state.duration) return toast("Chưa có bài hát — thêm bài ở bước 1 trước.", true);
  const mode = sepMode();
  $("btnSeparate").disabled = true;
  try {
    const { job } = await postJSON("/api/separate", { mode });
    pollJob(job, $("sepProgress"), () => {
      state.instReady = true;
      $("instPlayer").src = bust("/api/audio/inst");
      $("instInfo").hidden = false;
      $("btnSeparate").disabled = false;
      toast(mode === "ai" ? "Tách beat AI xong!" : "Tách beat nhanh xong!");
    }, (e) => { $("btnSeparate").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnSeparate").disabled = false;
    toast(err.message, true);
  }
});

/* ---------- Lời ---------- */
function refreshRenderBtn() {
  const ready = state.lines.length > 0 &&
    state.lines.every((l) => l.start != null);
  $("btnRender").disabled = !ready;
}
function setLines(lines, withTimes) {
  state.lines = lines.map((l) => ({
    text: l.text, start: withTimes ? l.start : null, words: l.words || null,
  }));
  state.tapIndex = 0; state.tapping = false; tapAudio.pause();
  $("btnTap").textContent = "▶ Phát & căn nhịp";
  $("btnTapUndo").disabled = true;
  $("btnTapRestart").disabled = !state.lines.length;
  renderLineList(); updateTapStatus();
  if (withTimes) state.tapped = true;
  refreshRenderBtn();
}
function renderLineList() {
  const box = $("lineList");
  box.innerHTML = "";
  state.lines.forEach((ln, i) => {
    const row = document.createElement("div");
    row.className = "linerow" + (i === state.tapIndex && state.tapping ? " cur" : "");
    const time = document.createElement("span");
    time.className = "ltime";
    time.textContent = ln.start == null ? "--:--" : fmt(ln.start);
    const txt = document.createElement("span");
    txt.className = "ltext"; txt.textContent = ln.text;
    row.append(time, txt);
    if (ln.start != null) {
      const mk = (label, d) => {
        const b = document.createElement("button");
        b.textContent = label; b.title = "Chỉnh giờ câu này";
        b.onclick = () => { nudge(i, d); };
        return b;
      };
      row.append(mk("−0,1s", -0.1), mk("+0,1s", 0.1));
    }
    box.appendChild(row);
  });
  const cur = state.lines[state.tapIndex];
  $("tapCurrent").textContent = state.tapping && cur ? "Câu sắp hát: " + cur.text
    : state.lines.length ? "Sẵn sàng căn nhịp" : "—";
}
function nudge(i, d) {
  const ln = state.lines[i];
  if (ln.start == null) return;
  ln.start = Math.max(0, Math.min(state.duration || 1e9, ln.start + d));
  renderLineList();
}
function updateTapStatus() {
  const done = state.lines.filter((l) => l.start != null).length;
  $("tapStatus").textContent = `Đã căn ${done}/${state.lines.length} câu`;
  const all = state.lines.length > 0 && done === state.lines.length;
  if (all && !state.tapped) {
    state.tapped = true;
    toast("Căn nhịp xong! Chỉnh phong cách ở bước 3 rồi xuất video thôi.");
  }
  refreshRenderBtn();
}
const SECTION_RE = /^(lyrics?|verse|chorus|hook|bridge|intro|outro|pre[-\s]?chorus|post[-\s]?chorus|refrain|điệp khúc|lời|phần|đoạn)\b/i;
function cleanLyricLines(arr) {
  // Bỏ dòng rác khi dán lời: nhãn mục Musixmatch (--:--Verse 1:), [Chorus],
  // đường gạch trang trí... — chỉ giữ câu hát thật.
  const out = [];
  for (let s of arr) {
    s = (s || "").trim();
    if (!s) continue;
    if (/^[-=*_~.·•\s]+$/.test(s)) continue;
    if (/^[\[(].{0,40}[\])]$/.test(s) && s.split(/\s+/).length <= 6) continue;
    if (s.length <= 30 && /:$/.test(s) && SECTION_RE.test(s)) continue;
    if (s.startsWith("--:--")) {
      const rest = s.slice(5).trim();
      if (!rest || SECTION_RE.test(rest) || (rest.length <= 30 && /:$/.test(rest))) continue;
      s = rest;
    }
    if (s) out.push(s);
  }
  return out;
}
$("btnUseLyrics").addEventListener("click", () => {
  const all = $("lyricsText").value.split("\n").map((s) => s.trim()).filter(Boolean);
  const raw = cleanLyricLines(all);
  if (!raw.length) return toast("Chưa có dòng lời nào (toàn dòng tiêu đề?).", true);
  setLines(raw.map((text) => ({ text })), false);
  const dropped = all.length - raw.length;
  $("lyricsOk").textContent = `Đã nhận ${raw.length} câu` +
    (dropped > 0 ? ` (tự bỏ ${dropped} dòng tiêu đề/rác)` : "") +
    " — bấm Tự căn nhịp bằng AI.";
});
$("btnAutoAlign").addEventListener("click", async () => {
  if (!state.lines.length) return toast("Chưa có lời — dán lời ở bước 2 trước.", true);
  if (!state.duration) return toast("Chưa có bài hát — thêm bài ở bước 1 trước.", true);
  $("btnAutoAlign").disabled = true;
  try {
    const { job } = await postJSON("/api/auto-align",
      { lines: state.lines.map((l) => l.text) });
    pollJob(job, $("alignProgress"), (res) => {
      $("btnAutoAlign").disabled = false;
      setLines(res.lines, true);
      const pct = Math.round((res.matched || 0) * 100);
      if (pct >= 50) {
        toast(`AI căn xong (khớp ${pct}% số từ). Nghe thử — câu nào lệch thì bấm −0,1s/+0,1s ở câu đó.`);
      } else {
        toast(`AI căn xong nhưng chỉ khớp ${pct}% số từ — có thể lời chưa đúng bài. Kiểm tra kỹ từng câu hoặc căn tay.`, true);
      }
    }, (e) => { $("btnAutoAlign").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoAlign").disabled = false;
    toast(err.message, true);
  }
});
$("lrcFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const data = await postRaw("/api/lrc", file, {});
    setLines(data.lines, true);
    $("lyricsOk").textContent = `Đã nạp ${data.lines.length} câu có sẵn mốc giờ — khỏi căn nhịp, xuống bước 3.`;
    renderLineList(); updateTapStatus();
    toast("Nạp .lrc thành công!");
  } catch (err) { toast(err.message, true); }
});

/* ---------- Căn nhịp bằng tay ---------- */
function tapSource() { return state.instReady ? "/api/audio/inst" : "/api/audio/song"; }
$("btnTap").addEventListener("click", async () => {
  if (!state.lines.length) return toast("Chưa có lời — làm bước 2 trước.", true);
  if (!state.tapping) {
    if (!tapAudio.src || !tapAudio.src.includes(tapSource()))
      tapAudio.src = bust(tapSource());
    state.tapping = true;
    $("btnTap").textContent = "⏺ Đang căn — bấm khi câu bắt đầu (Space)";
    $("btnTapUndo").disabled = state.tapIndex === 0;
    $("btnTapRestart").disabled = false;
    renderLineList();
    try { await tapAudio.play(); } catch (e) { toast("Không phát được nhạc: " + e.message, true); }
  } else {
    doTap();
  }
});
function doTap() {
  if (!state.tapping || state.tapIndex >= state.lines.length) return;
  state.lines[state.tapIndex].start = tapAudio.currentTime;
  state.tapIndex++;
  $("btnTapUndo").disabled = state.tapIndex === 0;
  if (state.tapIndex >= state.lines.length) {
    state.tapping = false;
    tapAudio.pause();
    $("btnTap").textContent = "▶ Phát & căn nhịp";
  }
  renderLineList(); updateTapStatus();
}
$("btnTapUndo").addEventListener("click", () => {
  if (state.tapIndex <= 0) return;
  state.tapIndex--;
  state.lines[state.tapIndex].start = null;
  state.tapped = false;
  $("btnTapUndo").disabled = state.tapIndex === 0;
  renderLineList(); updateTapStatus();
});
$("btnTapRestart").addEventListener("click", () => {
  state.lines.forEach((l) => (l.start = null));
  state.tapIndex = 0; state.tapped = false; state.tapping = false;
  tapAudio.pause(); tapAudio.currentTime = 0;
  $("btnTap").textContent = "▶ Phát & căn nhịp";
  $("btnTapUndo").disabled = true;
  renderLineList(); updateTapStatus();
});
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && state.tapping &&
      !/TEXTAREA|INPUT/.test(document.activeElement.tagName)) {
    e.preventDefault(); doTap();
  }
});
tapAudio.addEventListener("ended", () => {
  if (state.tapping) {
    state.tapping = false;
    $("btnTap").textContent = "▶ Phát & căn nhịp";
    renderLineList();
  }
});

/* ---------- Phong cách ---------- */
const PRESETS = [
  { name: "Vàng Cổ Điển", color: "#FFD400", base: "#FFFFFF", font: "Arial", size: 64, outline: 3 },
  { name: "Neon Hồng", color: "#FF2E88", base: "#E8E8FF", font: "Segoe UI", size: 68, outline: 4 },
  { name: "Ngọc Biển", color: "#00E5FF", base: "#FFFFFF", font: "Tahoma", size: 64, outline: 3 },
  { name: "Tím Mộng", color: "#B388FF", base: "#F3E5F5", font: "Segoe UI", size: 66, outline: 3 },
  { name: "Đỏ Rượu", color: "#FF5252", base: "#FFE0B2", font: "Times New Roman", size: 68, outline: 3 },
  { name: "Trắng Tối Giản", color: "#FFFFFF", base: "#9E9E9E", font: "Verdana", size: 60, outline: 2 },
  { name: "Xanh Lá Tươi", color: "#69F0AE", base: "#FFFFFF", font: "Arial", size: 64, outline: 3 },
  { name: "Cam Hoàng Hôn", color: "#FF9100", base: "#FFF3E0", font: "Tahoma", size: 66, outline: 3 },
  { name: "Hồng Phấn", color: "#FF80AB", base: "#FFFFFF", font: "Segoe UI", size: 66, outline: 3 },
  { name: "Xanh Đêm", color: "#40C4FF", base: "#E1F5FE", font: "Verdana", size: 62, outline: 3 },
];
function applyPreset(p, btn) {
  state.color = p.color; state.baseColor = p.base; state.outlineW = p.outline;
  $("fontSel").value = p.font;
  $("fontSize").value = p.size; $("sizeVal").textContent = p.size;
  document.querySelectorAll(".sw").forEach((x) =>
    x.classList.toggle("active", x.dataset.color === p.color));
  document.querySelectorAll(".preset").forEach((x) => x.classList.remove("active"));
  if (btn) btn.classList.add("active");
  saveStyle();
}
PRESETS.forEach((p, i) => {
  const b = document.createElement("button");
  b.className = "preset" + (i === 0 ? " active" : "");
  b.innerHTML = `<span class="dot" style="background:${p.color}"></span>` +
    `<span class="dot" style="background:${p.base}"></span> ${escHtml(p.name)}`;
  b.onclick = () => applyPreset(p, b);
  $("presetGrid").appendChild(b);
});

const GRADS = [
  ["demtim", "Đêm tím", "#0d0518", "#3d1470", "#8b3fbf"],
  ["hoanghon", "Hoàng hôn", "#1d0b38", "#b7416b", "#f7b733"],
  ["biensau", "Biển sâu", "#02101f", "#0a4d68", "#088f8f"],
  ["rungdem", "Rừng đêm", "#04140a", "#14532d", "#3f9d4e"],
  ["neon", "Hồng neon", "#0f0219", "#7b1e6e", "#ff2e88"],
  ["thanhpho", "Đêm đô thị", "#050914", "#1b2a6b", "#3d5afe"],
  ["vangkim", "Vàng kim", "#140b02", "#6e4410", "#d9a441"],
  ["hongdao", "Hồng đào", "#1c0714", "#83325c", "#f78fb3"],
  ["xanhmint", "Xanh mint", "#02120e", "#0b5563", "#2ec4b6"],
  ["domlua", "Đốm lửa", "#120202", "#7a1f0d", "#f46036"],
];
GRADS.forEach(([kind, label, c1, c2, c3]) => {
  const b = document.createElement("button");
  b.className = "grad" + (kind === state.gradKind ? " active" : "");
  b.dataset.g = kind;
  b.style.setProperty("--g1", c1);
  b.style.setProperty("--g2", c2);
  b.style.setProperty("--g3", c3);
  b.textContent = label;
  $("gradRow").appendChild(b);
});
$("gradRow").addEventListener("click", (e) => {
  const b = e.target.closest(".grad");
  if (!b) return;
  document.querySelectorAll(".grad").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.gradKind = b.dataset.g;
  const t = document.querySelector('input[name="bgtype"]:checked').value;
  if (t !== "gradient" && t !== "gradient_anim")
    document.querySelector('input[name="bgtype"][value="gradient"]').checked = true;
  saveStyle();
});
$("ratioSeg").addEventListener("click", (e) => {
  const b = e.target.closest(".seg");
  if (!b) return;
  document.querySelectorAll(".seg").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.ratio = b.dataset.ratio;
  saveStyle();
});
function collectStyle() {
  return {
    color: state.color, base_color: state.baseColor,
    size: Number($("fontSize").value), font: $("fontSel").value,
    effect: $("effectSel").value, fade: $("fadeChk").checked,
    two_line: $("twoLineChk").checked, outline_w: state.outlineW,
    countdown: $("countdownChk").checked,
    progress_bar: $("progressChk").checked,
    ratio: state.ratio,
    duet_color: $("duetChk").checked ? $("duetSel").value : null,
  };
}
function currentBg() {
  const t = document.querySelector('input[name="bgtype"]:checked').value;
  if (t === "gradient" || t === "gradient_anim")
    return { type: t, value: state.gradKind };
  return { type: t, value: "#0b0e1a" };
}
$("colorSwatches").addEventListener("click", (e) => {
  const b = e.target.closest(".sw");
  if (!b) return;
  document.querySelectorAll(".sw").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.color = b.dataset.color;
  saveStyle();
});
$("fontSize").addEventListener("input", (e) => {
  $("sizeVal").textContent = e.target.value;
  saveStyle();
});
$("duetChk").addEventListener("change", () => {
  $("duetRow").hidden = !$("duetChk").checked;
  saveStyle();
});
document.querySelectorAll('input[name="bgtype"]').forEach((r) =>
  r.addEventListener("change", () => updatePreview()));

/* Nhớ lựa chọn phong cách cho lần mở app sau (khỏi chọn lại). */
function saveStyle() {
  try {
    localStorage.setItem("km_style_v1", JSON.stringify({
      color: state.color, base: state.baseColor, outline: state.outlineW,
      font: $("fontSel").value, size: $("fontSize").value,
      effect: $("effectSel").value, fade: $("fadeChk").checked,
      two: $("twoLineChk").checked, grad: state.gradKind,
      countdown: $("countdownChk").checked, progress: $("progressChk").checked,
      duet: $("duetChk").checked, duetColor: $("duetSel").value,
      ratio: state.ratio,
    }));
  } catch (e) { /* bộ nhớ bị tắt/đầy thì bỏ qua, không chặn app */ }
  updatePreview();
}
function restoreStyle() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem("km_style_v1") || "null"); } catch (e) { }
  if (!s) { updatePreview(); return; }
  if (s.color) state.color = s.color;
  if (s.base) state.baseColor = s.base;
  if (s.outline) state.outlineW = s.outline;
  if (s.font) $("fontSel").value = s.font;
  if (s.size) { $("fontSize").value = s.size; $("sizeVal").textContent = s.size; }
  if (s.effect) $("effectSel").value = s.effect;
  $("fadeChk").checked = !!s.fade;
  $("twoLineChk").checked = !!s.two;
  $("countdownChk").checked = !!s.countdown;
  $("progressChk").checked = !!s.progress;
  $("duetChk").checked = !!s.duet;
  if (s.duetColor) $("duetSel").value = s.duetColor;
  $("duetRow").hidden = !$("duetChk").checked;
  if (s.ratio && ["16:9", "9:16", "1:1"].includes(s.ratio)) {
    state.ratio = s.ratio;
    document.querySelectorAll(".seg").forEach((x) =>
      x.classList.toggle("active", x.dataset.ratio === s.ratio));
  }
  document.querySelectorAll(".sw").forEach((x) =>
    x.classList.toggle("active", x.dataset.color === state.color));
  document.querySelectorAll(".preset").forEach((x) => x.classList.remove("active"));
  if (s.grad) {
    state.gradKind = s.grad;
    document.querySelectorAll(".grad").forEach((x) =>
      x.classList.toggle("active", x.dataset.g === s.grad));
  }
  updatePreview();
}
["fontSel", "effectSel", "fadeChk", "twoLineChk", "countdownChk",
 "progressChk", "duetSel"].forEach((id) =>
  $(id).addEventListener("change", saveStyle));

/* ---------- Xem trước trực tiếp ---------- */
const PV_WORDS = ["Ngày", "mai", "em", "đi", "biển", "nhớ", "tên", "em", "gọi", "về"];
const PV_NEXT = "Sóng hát lời ca ru êm đềm chiều nay";
function updatePreview() {
  const box = $("pvBox");
  if (!box) return;
  const st = collectStyle();
  const dims = { "16:9": [1920, 1080], "9:16": [1080, 1920], "1:1": [1080, 1080] };
  const [px, py] = dims[st.ratio] || dims["16:9"];
  box.style.aspectRatio = px + " / " + py;
  box.style.maxWidth = st.ratio === "9:16" ? "330px"
    : st.ratio === "1:1" ? "500px" : "100%";
  box.style.margin = "0 auto";
  const bg = currentBg();
  if (bg.type === "gradient" || bg.type === "gradient_anim") {
    const g = GRADS.find((x) => x[0] === state.gradKind) || GRADS[0];
    box.style.background = `linear-gradient(150deg, ${g[2]}, ${g[3]} 55%, ${g[4]})`;
    $("pvTag").textContent = bg.type === "gradient_anim" ? "Nền động" : "";
  } else if (bg.type === "color") {
    box.style.background = "#0b0e1a";
    $("pvTag").textContent = "";
  } else {
    box.style.background = "#232a45";
    $("pvTag").textContent = bg.type === "image" ? "Nền: ảnh của bạn" : "Nền: video của bạn";
  }
  $("pvBar").hidden = !st.progress_bar;
  $("pvDots").hidden = !st.countdown;
  const scale = (box.clientWidth || 600) / px;
  const fs = Math.max(11, Math.round(Number(st.size) * scale));
  const line = $("pvLine");
  line.style.fontFamily = st.font;
  line.style.fontSize = fs + "px";
  const sungN = 4;
  line.innerHTML = PV_WORDS.map((w, i) => {
    const col = i < sungN ? st.color : st.base_color;
    const cls = st.effect === "zoom" && i === sungN - 1 ? ' class="cur"' : "";
    return `<span${cls} style="color:${col}">${w}</span>`;
  }).join(" ");
  const nxt = $("pvNext");
  nxt.style.display = st.two_line ? "" : "none";
  nxt.style.fontFamily = st.font;
  nxt.style.fontSize = Math.max(9, Math.round(fs * 0.62)) + "px";
  const duet = st.duet_color;
  nxt.innerHTML = PV_NEXT.split(" ").map((w) =>
    `<span style="color:${duet || st.base_color}">${w}</span>`).join(" ");
}
window.addEventListener("resize", () => updatePreview());

async function uploadBg(file, kind) {
  const data = await postRaw("/api/upload-bg-" + kind, file,
    { "X-File-Name": encodeURIComponent(file.name) });
  $("bgOk").textContent = "Đã tải " + (kind === "image" ? "ảnh" : "video") + " nền: " + data.name;
  document.querySelector(`input[name="bgtype"][value="${kind}"]`).checked = true;
  updatePreview();
}
$("bgImageFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "image").catch((err) => toast(err.message, true)));
$("bgVideoFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "video").catch((err) => toast(err.message, true)));
$("guide").addEventListener("input", (e) => ($("guideVal").textContent = e.target.value + "%"));

/* ---------- Tự hành / tự động ---------- */
function handleAutoResult(res, okEl) {
  state.instReady = true;
  $("instPlayer").src = bust("/api/audio/inst");
  $("instInfo").hidden = false;
  fetch("/api/state").then((r) => r.json()).then((s) => {
    if (s && s.duration) state.duration = s.duration;
    if (s && s.song_name) {
      $("songName").textContent = s.song_name;
      $("songDur").textContent = fmt(state.duration);
      $("songInfo").hidden = false;
    }
  }).catch(() => { });
  $("songPlayer").src = bust("/api/audio/song");
  setLines(res.lines, true);
  $("renderDone").hidden = false;
  const vid = $("outVideo");
  vid.style.aspectRatio = state.ratio.replace(":", " / ");
  vid.src = bust(res.video || "/api/video");
  okEl.textContent = res.source === "ai"
    ? `Xong! AI tự chép & căn ${res.count} câu. Nghe thử — sai chữ ở đâu thì sửa lời ở bước 2 rồi bấm Tự căn nhịp bằng AI.`
    : `Xong! Dùng lời bạn dán, AI khớp ${Math.round((res.matched || 0) * 100)}% số từ, ${res.count} câu.`;
  toast("Video karaoke xong! 🎉 Bấm Lưu video vào máy ở bước 3 nhé.");
}
$("btnAutoAll").addEventListener("click", async () => {
  if (!state.duration) return toast("Chưa có bài hát — chọn file trước.", true);
  $("btnAutoAll").disabled = true;
  $("autoOk").textContent = "";
  try {
    const { job } = await postJSON("/api/auto-all", {
      lyrics: state.lines.length ? state.lines.map((l) => l.text) : null,
      sep_mode: sepMode(),
      style: collectStyle(),
      title: $("songTitle").value.trim(),
      guide: Number($("guide").value),
      bg: currentBg(),
    });
    pollJob(job, $("autoProgress"), (res) => {
      $("btnAutoAll").disabled = false;
      handleAutoResult(res, $("autoOk"));
    }, (e) => { $("btnAutoAll").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoAll").disabled = false;
    toast(err.message, true);
  }
});
$("btnAutoLink").addEventListener("click", async () => {
  const urls = $("ytUrls").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return toast("Chưa dán link YouTube.", true);
  const common = {
    want_video: $("ytVideoBg").checked,
    sep_mode: sepMode(),
    style: collectStyle(),
    guide: Number($("guide").value),
    bg: currentBg(),
  };
  $("btnAutoLink").disabled = true;
  $("autoLinkOk").textContent = "";
  if (urls.length > 1) {
    try {
      await postJSON("/api/batch", { urls, ...common });
      $("batchBox").hidden = false;
      startBatchPoll();
    } catch (err) {
      $("btnAutoLink").disabled = false;
      toast(err.message, true);
    }
    return;
  }
  try {
    const { job } = await postJSON("/api/auto-link", {
      url: urls[0],
      lyrics: state.lines.length ? state.lines.map((l) => l.text) : null,
      title: $("songTitle").value.trim(),
      ...common,
    });
    pollJob(job, $("autoLinkProgress"), (res) => {
      $("btnAutoLink").disabled = false;
      handleAutoResult(res, $("autoLinkOk"));
    }, (e) => { $("btnAutoLink").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoLink").disabled = false;
    toast(err.message, true);
  }
});

/* ---------- Hàng loạt ---------- */
let batchTimer = null;
function renderBatch(items) {
  const box = $("batchList");
  box.innerHTML = "";
  for (const it of items) {
    const div = document.createElement("div");
    div.className = "batch-item";
    const name = escHtml(it.title || it.url || "Bài hát");
    const kindTag = it.kind === "file" ? "📁 " : "";
    let badge, extra = "";
    if (it.status === "done") {
      badge = '<span class="badge ok">✓ Xong</span>';
      extra = `<button class="bsave primary" data-id="${it.id}">💾 Lưu video</button>
               <a class="dl" href="/api/batch/${it.id}/download">⬇ Tải</a>
               <a class="dl" href="/api/batch/${it.id}/video" target="_blank">▶ Xem</a>`;
    } else if (it.status === "error") {
      badge = '<span class="badge err">✗ Lỗi</span>';
      extra = `<span class="err-text">${escHtml(it.error || "")}</span>`;
    } else if (it.status === "running") {
      badge = `<span class="badge run">Đang chạy ${Math.round(it.progress)}%</span>`;
      extra = `<span class="run-label">${escHtml(it.label || "")}</span>`;
    } else {
      badge = '<span class="badge wait">Chờ lượt</span>';
    }
    div.innerHTML = `<div class="batch-head"><span class="batch-name">${kindTag}${name}</span>${badge}</div>
      <div class="progress batch-bar"><div class="bar" style="width:${it.progress || 0}%"></div></div>
      <div class="batch-extra">${extra}</div>`;
    box.appendChild(div);
  }
  box.querySelectorAll(".bsave").forEach((b) =>
    b.addEventListener("click", () => saveBatchItem(b)));
}
async function saveBatchItem(btn) {
  btn.disabled = true;
  try {
    const data = await postJSON("/api/batch/" + btn.dataset.id + "/save", {});
    toast("Đã lưu: " + data.path);
  } catch (err) {
    toast(err.message, true);
  }
  btn.disabled = false;
}
async function pollBatch() {
  try {
    const data = await (await fetch("/api/batch")).json();
    renderBatch(data.items || []);
    const active = (data.items || []).some(
      (i) => i.status === "queued" || i.status === "running");
    if (!active && batchTimer) {
      clearInterval(batchTimer);
      batchTimer = null;
      $("btnAutoLink").disabled = false;
      toast("Hàng loạt xong hết! 🎉");
    }
  } catch (e) { /* server bận — lần poll sau thử lại */ }
}
function startBatchPoll() {
  pollBatch();
  if (batchTimer) clearInterval(batchTimer);
  batchTimer = setInterval(pollBatch, 2000);
}
$("batchFiles").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (!files.length) return;
  const opts = {
    sep_mode: sepMode(), style: collectStyle(),
    guide: Number($("guide").value), bg: currentBg(),
  };
  let ok = 0;
  for (const f of files) {
    try {
      await postRaw("/api/batch-file", f, {
        "X-File-Name": encodeURIComponent(f.name),
        "X-Batch-Opts": JSON.stringify(opts),
      });
      ok++;
    } catch (err) {
      toast("File " + f.name + ": " + err.message, true);
    }
  }
  if (ok) {
    $("batchFileOk").textContent = `Đã thêm ${ok} file vào hàng loạt.`;
    $("batchBox").hidden = false;
    startBatchPoll();
  }
});

/* ---------- Xuất video ---------- */
$("btnRender").addEventListener("click", async () => {
  const missing = state.lines.filter((l) => l.start == null).length;
  if (missing) return toast(`Còn ${missing} câu chưa căn nhịp.`, true);
  $("btnRender").disabled = true;
  try {
    const style = collectStyle();
    const title = $("songTitle").value.trim();
    if (title) style.title = title;
    const { job } = await postJSON("/api/render", {
      lines: state.lines.map((l) => ({ start: l.start, text: l.text, words: l.words })),
      style,
      guide: Number($("guide").value),
      bg: currentBg(),
      audio: state.instReady ? "inst" : "orig",
    });
    pollJob(job, $("renderProgress"), () => {
      $("renderDone").hidden = false;
      const vid = $("outVideo");
      vid.style.aspectRatio = state.ratio.replace(":", " / ");
      vid.src = bust("/api/video");
      $("btnRender").disabled = false;
      toast("Xuất video xong! 🎉 Bấm Lưu video vào máy nhé.");
    }, (e) => { $("btnRender").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnRender").disabled = false;
    toast(err.message, true);
  }
});
$("btnSaveVideo").addEventListener("click", async () => {
  $("btnSaveVideo").disabled = true;
  try {
    const data = await postJSON("/api/save-video", {});
    $("saveOk").textContent = "Đã lưu: " + data.path;
    toast("Đã lưu video vào máy: " + data.path);
  } catch (err) {
    toast(err.message, true);
  }
  $("btnSaveVideo").disabled = false;
});
$("btnOpenFolder").addEventListener("click", async () => {
  try {
    await postJSON("/api/open-folder", {});
  } catch (err) {
    toast(err.message, true);
  }
});

restoreStyle();
refreshRenderBtn();
