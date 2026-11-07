"use strict";
/* Karaoke Maker v4 — Thư viện / Studio / Xuất.
   Mọi luồng xử lý của v3 (link tự hành, hàng loạt, tách beat, AI căn lời,
   căn tay Space, mẫu chữ/nền, lưu video) giữ nguyên, khoác khung mới. */
const $ = (id) => document.getElementById(id);
const state = {
  projectId: null, duration: 0, instReady: false, hasSong: false,
  lines: [], selLine: 0, tapIndex: 0, tapping: false,
  color: "#FFD400", baseColor: "#FFFFFF", outlineW: 3,
  gradKind: "demtim", ratio: "16:9", sepMode: "ai",
  projects: [], storage: null, saveTimer: null, saveDirty: false,
};
const audio = () => $("studioAudio");

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.style.borderColor = isErr ? "var(--err)" : "var(--ok)";
  t.hidden = false;
  clearTimeout(toast._h);
  toast._h = setTimeout(() => (t.hidden = true), 4200);
}
function fmt(s) {
  if (!isFinite(s) || s == null) return "0:00";
  s = Math.max(0, Math.round(s));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function fmtBytes(b) {
  if (!b && b !== 0) return "—";
  if (b >= 1e9) return (b / 1e9).toFixed(1).replace(".", ",") + " GB";
  if (b >= 1e6) return Math.round(b / 1e6) + " MB";
  return Math.max(1, Math.round(b / 1e3)) + " KB";
}
function bust(url) { return url + "?v=" + Date.now(); }
function escHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function stripAcc(s) {
  return String(s || "").toLowerCase().normalize("NFD")
    .replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
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
async function getJSON(url) {
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Lỗi " + r.status));
  return data;
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
        // Lỗi phải HIỆN RÕ và NẰM LẠI — toast thoáng qua làm người dùng
        // tưởng app "im luôn" không rõ chuyện gì.
        clearInterval(iv);
        progressEl.classList.add("err");
        bar.style.width = "100%";
        pct.textContent = "✗ " + (job.error || "Lỗi không rõ");
        (onErr || ((e) => toast(e, true)))(job.error || "Lỗi không rõ");
      }
    } catch (e) {
      // Không nuốt lặng vô hạn: mất kết nối nhiều nhịp = app có thể đã tắt.
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

/* ---------- Điều hướng ---------- */
function showView(name) {
  for (const v of ["viewLibrary", "viewStudio", "viewExport", "viewSettings"])
    $(v).hidden = true;
  $("view" + name[0].toUpperCase() + name.slice(1)).hidden = false;
  $("navLibrary").classList.toggle("active", name === "library");
  $("navProjects").classList.toggle("active", name === "library");
  $("navQueue").classList.toggle("active", name === "export");
  $("navSettings").classList.toggle("active", name === "settings");
  if (name !== "studio") { const a = audio(); if (a) a.pause(); }
  window.scrollTo(0, 0);
}
$("navLibrary").addEventListener("click", () => { showView("library"); loadLibrary(); });
$("navProjects").addEventListener("click", () => {
  showView("library"); libShowAll = true; loadLibrary();
  $("projCards").scrollIntoView({ behavior: "smooth" });
});
$("navQueue").addEventListener("click", () => {
  if (state.projectId) openExport();
  else { showView("library"); toast("Mở một project trước để xem hàng đợi xuất theo bài, hoặc bấm vào bài bất kỳ trong Thư viện."); loadLibrary(); refreshQueueBadge(); showQueueOnly(); }
});
$("navSettings").addEventListener("click", openSettings);
$("btnBackLib").addEventListener("click", () => { showView("library"); loadLibrary(); });
$("btnBackLib2").addEventListener("click", () => { showView("library"); loadLibrary(); });
$("btnBackStudio").addEventListener("click", () => showView("studio"));
$("btnGoExport").addEventListener("click", openExport);
function showQueueOnly() { /* hàng đợi xem ở màn Xuất */ }

/* ---------- Cách tách beat (đồng bộ 3 cụm radio) ---------- */
function syncSepRadios() {
  document.querySelectorAll('input[name="sepmode"], input[name="sepmodeS"], input[name="sepmodeSet"]')
    .forEach((r) => (r.checked = r.value === state.sepMode));
}
document.querySelectorAll('input[name="sepmode"], input[name="sepmodeS"], input[name="sepmodeSet"]')
  .forEach((r) => r.addEventListener("change", () => {
    state.sepMode = r.value; syncSepRadios();
  }));
function sepMode() { return state.sepMode; }

/* ================= PHONG CÁCH (dùng chung) ================= */
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
function gradCss(kind) {
  const g = GRADS.find((x) => x[0] === kind) || GRADS[0];
  return `linear-gradient(150deg, ${g[2]}, ${g[3]} 55%, ${g[4]})`;
}
function gradForTitle(title) {
  let h = 0;
  for (const c of String(title || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return GRADS[h % GRADS.length][0];
}
PRESETS.forEach((p, i) => {
  const b = document.createElement("button");
  b.className = "preset" + (i === 0 ? " active" : "");
  b.innerHTML = `<span class="dot" style="background:${p.color}"></span>` +
    `<span class="dot" style="background:${p.base}"></span> ${escHtml(p.name)}`;
  b.onclick = () => applyPreset(p, b);
  $("presetGrid").appendChild(b);
});
function applyPreset(p, btn) {
  state.color = p.color; state.baseColor = p.base; state.outlineW = p.outline;
  if ([...$("fontSel").options].some((o) => o.value === p.font))
    $("fontSel").value = p.font;
  $("fontSize").value = p.size; $("sizeVal").textContent = p.size;
  markSwatches();
  document.querySelectorAll(".preset").forEach((x) => x.classList.remove("active"));
  if (btn) btn.classList.add("active");
  saveStyle();
}
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
  state.gradKind = b.dataset.g;
  document.querySelectorAll(".grad").forEach((x) =>
    x.classList.toggle("active", x.dataset.g === state.gradKind));
  const t = $("bgTypeSel").value;
  if (t !== "gradient" && t !== "gradient_anim") $("bgTypeSel").value = "gradient";
  saveStyle();
});
$("ratioSeg").addEventListener("click", (e) => {
  const b = e.target.closest(".seg");
  if (!b) return;
  state.ratio = b.dataset.ratio;
  document.querySelectorAll(".seg").forEach((x) =>
    x.classList.toggle("active", x.dataset.ratio === state.ratio));
  saveStyle();
});
function markSwatches() {
  document.querySelectorAll("#colorSwatches .sw").forEach((x) =>
    x.classList.toggle("active", x.dataset.color === state.color));
  document.querySelectorAll("#baseSwatches .swb").forEach((x) =>
    x.classList.toggle("active", x.dataset.color === state.baseColor));
}
$("colorSwatches").addEventListener("click", (e) => {
  const b = e.target.closest(".sw");
  if (!b) return;
  state.color = b.dataset.color; markSwatches(); saveStyle();
});
$("baseSwatches").addEventListener("click", (e) => {
  const b = e.target.closest(".swb");
  if (!b) return;
  state.baseColor = b.dataset.color; markSwatches(); saveStyle();
});
$("fontSize").addEventListener("input", (e) => {
  $("sizeVal").textContent = e.target.value; saveStyle();
});
$("bgBlur").addEventListener("input", (e) => {
  $("blurVal").textContent = e.target.value; saveStyle();
});
$("guide").addEventListener("input", (e) => {
  $("guideVal").textContent = e.target.value + "%"; scheduleSave();
});
$("duetChk").addEventListener("change", () => {
  $("duetBox").hidden = !$("duetChk").checked;
  renderLineList(); saveStyle();
});
$("bgTypeSel").addEventListener("change", saveStyle);
["fontSel", "effectSel", "fadeChk", "twoLineChk", "countdownChk",
 "progressChk", "duetSel"].forEach((id) =>
  $(id).addEventListener("change", saveStyle));

function collectStyle() {
  const duet = $("duetChk").checked;
  const st = {
    color: state.color, base_color: state.baseColor,
    size: Number($("fontSize").value), font: $("fontSel").value,
    effect: $("effectSel").value, fade: $("fadeChk").checked,
    two_line: $("twoLineChk").checked, outline_w: state.outlineW,
    countdown: $("countdownChk").checked,
    progress_bar: $("progressChk").checked,
    ratio: state.ratio,
    bg_blur: Number($("bgBlur").value),
    duet_color: duet ? $("duetSel").value : null,
  };
  if (duet) {
    st.duet_female_color = state.color;   // Nữ hát bằng màu chính (hồng)
    st.duet_male_color = $("duetSel").value;
  }
  return st;
}
function styleForRender() {
  const st = collectStyle();
  const title = $("songTitle").value.trim();
  if (title) st.title = title;
  return st;
}
function currentBg() {
  const t = $("bgTypeSel").value;
  if (t === "gradient" || t === "gradient_anim")
    return { type: t, value: state.gradKind };
  return { type: t, value: "#0b0e1a" };
}
function applyStyleToControls(style, bg, guide) {
  style = style || {}; bg = bg || {};
  if (style.color) state.color = style.color;
  if (style.base_color) state.baseColor = style.base_color;
  if (style.outline_w) state.outlineW = style.outline_w;
  if (style.font && [...$("fontSel").options].some((o) => o.value === style.font))
    $("fontSel").value = style.font;
  if (style.size) { $("fontSize").value = style.size; $("sizeVal").textContent = style.size; }
  if (style.effect) $("effectSel").value = style.effect;
  $("fadeChk").checked = style.fade !== false;
  $("twoLineChk").checked = style.two_line !== false;
  $("countdownChk").checked = !!style.countdown;
  $("progressChk").checked = !!style.progress_bar;
  const duet = !!(style.duet_color || style.duet_male_color);
  $("duetChk").checked = duet;
  $("duetBox").hidden = !duet;
  const male = style.duet_male_color || style.duet_color;
  if (male && [...$("duetSel").options].some((o) => o.value === male))
    $("duetSel").value = male;
  if (style.ratio && ["16:9", "9:16", "1:1"].includes(style.ratio)) {
    state.ratio = style.ratio;
    document.querySelectorAll(".seg").forEach((x) =>
      x.classList.toggle("active", x.dataset.ratio === state.ratio));
  }
  if (style.bg_blur != null) {
    $("bgBlur").value = style.bg_blur; $("blurVal").textContent = style.bg_blur;
  }
  if (bg.type) $("bgTypeSel").value = bg.type;
  if (bg.value && GRADS.some((g) => g[0] === bg.value)) {
    state.gradKind = bg.value;
    document.querySelectorAll(".grad").forEach((x) =>
      x.classList.toggle("active", x.dataset.g === state.gradKind));
  }
  if (guide != null) {
    $("guide").value = guide; $("guideVal").textContent = guide + "%";
  }
  markSwatches();
  updatePreview();
}
function saveStyle() {
  try {
    localStorage.setItem("km_style_v1", JSON.stringify({
      color: state.color, base: state.baseColor, outline: state.outlineW,
      font: $("fontSel").value, size: $("fontSize").value,
      effect: $("effectSel").value, fade: $("fadeChk").checked,
      two: $("twoLineChk").checked, grad: state.gradKind,
      countdown: $("countdownChk").checked, progress: $("progressChk").checked,
      duet: $("duetChk").checked, duetColor: $("duetSel").value,
      ratio: state.ratio, blur: $("bgBlur").value,
      bgType: $("bgTypeSel").value,
    }));
  } catch (e) { /* bộ nhớ bị tắt/đầy thì bỏ qua, không chặn app */ }
  updatePreview();
  scheduleSave();
}
function restoreStyle() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem("km_style_v1") || "null"); } catch (e) { }
  if (!s) { updatePreview(); return; }
  applyStyleToControls({
    color: s.color, base_color: s.base, outline_w: s.outline, font: s.font,
    size: s.size, effect: s.effect, fade: s.fade, two_line: s.two,
    countdown: s.countdown, progress_bar: s.progress,
    duet_color: s.duet ? s.duetColor : null,
    duet_male_color: s.duet ? s.duetColor : null,
    ratio: s.ratio, bg_blur: s.blur,
  }, { type: s.bgType || "gradient", value: s.grad || "demtim" }, 0);
}

/* ---------- Tự lưu project (autosave) ---------- */
function scheduleSave() {
  if (!state.projectId) return;
  state.saveDirty = true;
  $("saveChip").textContent = "Đang lưu…";
  $("saveChip").classList.add("saving");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(flushSave, 700);
}
async function flushSave() {
  if (!state.projectId || !state.saveDirty) return;
  clearTimeout(state.saveTimer);
  try {
    await postJSON("/api/project/current", {
      lines: state.lines, style: collectStyle(), bg: currentBg(),
      guide: Number($("guide").value),
      lyrics_text: $("lyricsText").value,
    });
    state.saveDirty = false;
    $("saveChip").textContent = "✓ Đã lưu tự động";
    $("saveChip").classList.remove("saving");
  } catch (e) {
    $("saveChip").textContent = "⚠ Chưa lưu được";
  }
}

/* ================= THƯ VIỆN ================= */
let libShowAll = false;
function srcLabel(p) {
  if (p.id === "default") return "Phiên làm việc";
  if (p.source_kind === "link") return "YouTube";
  if (p.source_kind === "file") return "File trên máy";
  if (p.source_kind === "empty") return "Dự án trống";
  return "—";
}
function statusChip(p) {
  if (p.corrupt) return '<span class="chip orange">⚠ File hỏng</span>';
  const s = p.status || {};
  if (s.exported) return '<span class="chip green">Đã xuất</span>';
  if (s.lyrics === "synced") return '<span class="chip green">Đã đồng bộ</span>';
  if (s.lyrics === "draft") return '<span class="chip orange">Đang sửa lời</span>';
  if (p.has_song) return '<span class="chip orange">Chưa đồng bộ</span>';
  return '<span class="chip gray">Bản nháp</span>';
}
function beatChip(p) {
  return p.status && p.status.beat
    ? '<span class="chip green plain">Đã tách ✓</span>'
    : '<span class="chip gray plain">Chưa tách</span>';
}
function lyricsChip(p) {
  const s = (p.status || {}).lyrics;
  if (s === "synced") return '<span class="chip green plain">Đã đồng bộ</span>';
  if (s === "draft") return '<span class="chip orange plain">Đang sửa</span>';
  return '<span class="chip gray plain">Chưa có</span>';
}
async function loadLibrary() {
  try {
    const data = await getJSON("/api/projects");
    state.projects = data.items || [];
    state.storage = data.storage || null;
    renderLibrary();
    refreshQueueBadge();
  } catch (e) { toast("Không tải được Thư viện: " + e.message, true); }
}
function filteredProjects() {
  const q = stripAcc($("libSearch").value.trim());
  if (!q) return state.projects;
  return state.projects.filter((p) => stripAcc(p.title).includes(q));
}
function renderLibrary() {
  const items = filteredProjects();
  const cards = libShowAll ? items : items.slice(0, 8);
  $("projCountTxt").textContent = state.projects.length
    ? `· ${state.projects.length} dự án` : "";
  $("songCountTxt").textContent = state.projects.length
    ? `${state.projects.length} bài` : "";
  $("navProjCount").hidden = !state.projects.length;
  $("navProjCount").textContent = state.projects.length;
  $("libEmpty").hidden = state.projects.length > 0;
  $("projCards").innerHTML = cards.map((p) => `
    <div class="pcard" data-open="${escHtml(p.id)}">
      <div class="thumb" style="background:${gradCss(p.grad || gradForTitle(p.title))}">
        <span class="play">▶</span><span class="ratio">${escHtml(p.ratio || "16:9")}</span>
        <b>${escHtml(p.title)}</b>
      </div>
      <div class="meta">
        <div class="sub">${escHtml(srcLabel(p))}${p.inst_mode ? " · Beat " + (p.inst_mode === "ai" ? "AI" : "nhanh") : ""}</div>
        <div class="foot">${statusChip(p)}<span class="dur">${p.duration ? fmt(p.duration) : ""}</span></div>
      </div>
      ${p.id !== "default" ? `<button class="del" data-del="${escHtml(p.id)}" title="Xoá project">✕</button>` : ""}
    </div>`).join("");
  $("songRows").innerHTML = items.map((p) => `
    <tr>
      <td><span class="note-ic">♪</span><span class="tname">${escHtml(p.title)}</span></td>
      <td>${escHtml(srcLabel(p))}</td>
      <td>${p.duration ? fmt(p.duration) : "—"}</td>
      <td>${p.corrupt ? '<span class="chip orange plain">⚠ Hỏng</span>' : beatChip(p)}</td>
      <td>${p.corrupt ? '<span class="chip gray plain">—</span>' : lyricsChip(p)}</td>
      <td style="text-align:right; white-space:nowrap">
        ${!p.corrupt && p.has_song && !(p.status || {}).beat ? `<button class="act gray" data-sep="${escHtml(p.id)}">Tách beat</button> · ` : ""}
        ${p.corrupt ? `<button class="act" data-del="${escHtml(p.id)}">Xoá</button>`
                     : `<button class="act" data-open="${escHtml(p.id)}">Mở studio</button>`}
      </td>
    </tr>`).join("");
  const st = state.storage;
  if (st) {
    const used = st.projects_bytes || 0, total = st.total || 0;
    $("storageFill").style.width = total ? Math.min(100, used / total * 100) + "%" : "0%";
    $("storageTxt").textContent = `${fmtBytes(used)} / ${fmtBytes(total)}`;
  }
}
$("libSearch").addEventListener("input", renderLibrary);
$("libShowAll").addEventListener("click", () => {
  libShowAll = !libShowAll;
  $("libShowAll").textContent = libShowAll ? "Thu gọn ←" : "Xem tất cả →";
  renderLibrary();
});
$("projCards").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); return deleteProject(del.dataset.del); }
  const card = e.target.closest("[data-open]");
  if (card) openProject(card.dataset.open);
});
$("songRows").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-del]");
  if (del) return deleteProject(del.dataset.del);
  const sep = e.target.closest("[data-sep]");
  if (sep) return separateProject(sep.dataset.sep);
  const op = e.target.closest("[data-open]");
  if (op) openProject(op.dataset.open);
});
async function deleteProject(pid) {
  const p = state.projects.find((x) => x.id === pid);
  if (!confirm(`Xoá project “${p ? p.title : pid}”? Toàn bộ file làm việc của bài này sẽ bị xoá.`))
    return;
  try {
    await postJSON(`/api/projects/${pid}/delete`, {});
    if (state.projectId === pid) state.projectId = null;
    toast("Đã xoá project.");
    loadLibrary();
  } catch (err) { toast(err.message, true); }
}
async function separateProject(pid) {
  try {
    const { job } = await postJSON(`/api/projects/${pid}/separate`,
      { mode: sepMode() });
    toast("Đang tách beat…");
    const iv = setInterval(async () => {
      try {
        const j = await (await fetch("/api/job/" + job)).json();
        if (j.status === "done") {
          clearInterval(iv); toast("Tách beat xong!"); loadLibrary();
        } else if (j.status === "error") {
          clearInterval(iv); toast(j.error || "Tách beat lỗi", true);
        }
      } catch (e) { clearInterval(iv); }
    }, 1200);
  } catch (err) { toast(err.message, true); }
}

/* ----- Tạo bài: link / file (luồng v3 giữ nguyên) ----- */
function showTab(link) {
  $("paneLink").hidden = !link;
  $("paneFile").hidden = link;
  $("tabLink").classList.toggle("active", link);
  $("tabFile").classList.toggle("active", !link);
}
$("tabLink").addEventListener("click", () => showTab(true));
$("tabFile").addEventListener("click", () => showTab(false));
$("btnCreate").addEventListener("click", () => {
  $("createPanel").hidden = !$("createPanel").hidden;
  if (!$("createPanel").hidden) $("createPanel").scrollIntoView({ behavior: "smooth" });
});
$("btnAutoLink").addEventListener("click", async () => {
  const urls = $("ytUrls").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!urls.length) return toast("Chưa dán link YouTube.", true);
  const common = {
    want_video: $("ytVideoBg").checked,
    sep_mode: sepMode(), style: collectStyle(), bg: currentBg(),
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
    const { job } = await postJSON("/api/projects/import-link",
      { url: urls[0], ...common });
    pollJob(job, $("autoLinkProgress"), () => {
      $("btnAutoLink").disabled = false;
      $("autoLinkOk").textContent = "Xong! Bài đã vào Thư viện.";
      toast("Làm video từ link xong! 🎉 Bài mới đã vào Thư viện.");
      loadLibrary();
    }, (e) => { $("btnAutoLink").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoLink").disabled = false;
    toast(err.message, true);
  }
});
async function importOneFile(file) {
  return postRaw("/api/projects/import-file", file,
    { "X-File-Name": encodeURIComponent(file.name) });
}
$("songFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  $("songDropText").textContent = "Đang nạp: " + file.name + " ...";
  try {
    const data = await importOneFile(file);
    $("songDropText").textContent = "Bấm để chọn 1 file nhạc / video — tạo project rồi mở Studio";
    toast("Đã tạo project từ file. Mở Studio để làm tiếp.");
    await loadLibrary();
    openProject(data.project.id);
  } catch (err) {
    $("songDropText").textContent = "Bấm để chọn 1 file nhạc / video — tạo project rồi mở Studio";
    toast(err.message, true);
  }
});
$("importFiles").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (!files.length) return;
  let ok = 0;
  for (const f of files) {
    try { await importOneFile(f); ok++; }
    catch (err) { toast(`File ${f.name}: ${err.message}`, true); }
  }
  if (ok) { toast(`Đã nhập ${ok} bài vào Thư viện.`); loadLibrary(); }
});
$("libMain").addEventListener("dragover", (e) => {
  e.preventDefault(); $("libMain").classList.add("dragover");
});
$("libMain").addEventListener("dragleave", () => $("libMain").classList.remove("dragover"));
$("libMain").addEventListener("drop", async (e) => {
  e.preventDefault(); $("libMain").classList.remove("dragover");
  const files = [...(e.dataTransfer.files || [])];
  if (!files.length) return;
  let ok = 0;
  for (const f of files) {
    try { await importOneFile(f); ok++; }
    catch (err) { toast(`File ${f.name}: ${err.message}`, true); }
  }
  if (ok) { toast(`Đã nhập ${ok} bài vào Thư viện.`); loadLibrary(); }
});

/* ----- Hàng loạt (v3) ----- */
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
      extra = `<button class="bsave btn grad small" data-id="${it.id}">💾 Lưu video</button>
               <a class="dl" href="/api/batch/${it.id}/download">⬇ Tải</a>
               <a class="dl" href="/api/batch/${it.id}/video" target="_blank">▶ Xem</a>` +
              (it.project_id ? ` <span class="ok">· đã vào Thư viện</span>` : "");
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
  } catch (err) { toast(err.message, true); }
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
      loadLibrary();
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
    } catch (err) { toast("File " + f.name + ": " + err.message, true); }
  }
  if (ok) {
    $("batchFileOk").textContent = `Đã thêm ${ok} file vào hàng loạt.`;
    $("batchBox").hidden = false;
    startBatchPoll();
  }
});

/* ================= STUDIO ================= */
async function openProject(pid) {
  try {
    const data = await postJSON(`/api/projects/${pid}/open`, {});
    state.projectId = pid;
    state.duration = data.duration || 0;
    state.instReady = !!data.inst_ready;
    state.hasSong = !!(data.project && data.project.has_song);
    state.lines = (data.lines || []).map((l) => ({
      text: l.text, start: l.start != null ? l.start : null,
      end: l.end != null ? l.end : null,
      words: l.words || null, voice: l.voice || null,
      ok: l.ok !== false,
    }));
    state.selLine = 0; state.tapIndex = 0; state.tapping = false;
    $("stTitle").textContent = data.project.title;
    const srcTxt = srcLabel(data.project);
    $("stSub").textContent = `${data.song_name || srcTxt} · ${fmt(state.duration)}` +
      (state.instReady ? ` · beat đã tách (${data.project.inst_mode === "ai" ? "AI" : "nhanh"})` : " · chưa tách beat");
    $("lyricsText").value = data.lyrics_text || "";
    $("dlBeat").hidden = !state.instReady;
    $("songTitle").value = "";
    applyStyleToControls(data.style, data.bg, data.guide);
    const a = audio();
    a.pause();
    if (state.hasSong)
      a.src = bust(state.instReady ? "/api/audio/inst" : "/api/audio/song");
    renderLineList();
    updateTapStatus();
    showView("studio");
    loadPeaks();
    updatePreview();
  } catch (err) { toast(err.message, true); }
}

/* ----- danh sách dòng lời ----- */
function lineEnd(i) {
  const l = state.lines[i];
  if (!l) return 0;
  if (l.end != null) return l.end;
  for (let j = i + 1; j < state.lines.length; j++)
    if (state.lines[j].start != null) return state.lines[j].start;
  return state.duration || l.start || 0;
}
function setLines(lines, withTimes) {
  state.lines = lines.map((l) => ({
    text: l.text,
    start: withTimes ? (l.start != null ? l.start : null) : null,
    end: withTimes ? (l.end != null ? l.end : null) : null,
    words: l.words || null, voice: l.voice || null,
    ok: l.ok !== false,
  }));
  state.tapIndex = 0; state.tapping = false;
  audio().pause();
  $("btnTap").textContent = "▶ Phát & gắn nhịp";
  $("btnTapUndo").disabled = true;
  $("btnTapRestart").disabled = !state.lines.length;
  state.selLine = 0;
  renderLineList(); updateTapStatus(); scheduleSave(); drawWave();
}
function renderLineList() {
  const box = $("lineList");
  box.innerHTML = "";
  const duet = $("duetChk").checked;
  let okN = 0, badN = 0;
  state.lines.forEach((ln, i) => {
    if (ln.start != null && ln.ok === false) badN++;
    else if (ln.start != null) okN++;
    const row = document.createElement("div");
    row.className = "linerow" + (i === state.selLine ? " sel" : "") +
      (state.tapping && i === state.tapIndex ? " cur" : "");
    const num = document.createElement("span");
    num.className = "lnum"; num.textContent = i + 1;
    const txt = document.createElement("span");
    txt.className = "ltext"; txt.textContent = ln.text;
    txt.title = "Bấm đúp để sửa lời";
    const side = document.createElement("span");
    side.className = "lside";
    if (duet) {
      const v = document.createElement("button");
      v.className = "voicechip" + (ln.voice ? " " + ln.voice : "");
      v.textContent = ln.voice === "f" ? "Nữ" : ln.voice === "m" ? "Nam" : "Giọng";
      v.title = "Gán giọng dòng này (Nữ / Nam / chưa gán)";
      v.onclick = (e) => { e.stopPropagation(); cycleVoice(i); };
      side.appendChild(v);
    }
    if (ln.start == null) {
      const w = document.createElement("span");
      w.className = "ltime"; w.textContent = "--:--";
      side.appendChild(w);
    } else if (ln.ok === false) {
      const w = document.createElement("span");
      w.className = "lwarn"; w.textContent = "⚠ Chưa khớp";
      w.title = "AI không khớp trực tiếp được dòng này (giờ đang nội suy) — nghe thử và chỉnh lại";
      side.appendChild(w);
    } else {
      const t = document.createElement("span");
      t.className = "ltime";
      t.textContent = `${fmt(ln.start)} – ${fmt(lineEnd(i))}`;
      side.appendChild(t);
    }
    if (ln.start != null) {
      const mk = (label, d) => {
        const b = document.createElement("button");
        b.className = "mini"; b.textContent = label; b.title = "Chỉnh giờ câu này";
        b.onclick = (e) => { e.stopPropagation(); nudge(i, d); };
        return b;
      };
      side.append(mk("−0,1s", -0.1), mk("+0,1s", 0.1));
    }
    row.append(num, txt, side);
    row.onclick = () => {
      state.selLine = i;
      renderLineList(); syncVoiceChips();
      if (ln.start != null && state.hasSong) {
        audio().currentTime = ln.start;
        updatePreview();
      }
    };
    txt.ondblclick = (e) => { e.stopPropagation(); editLineText(i, txt); };
    box.appendChild(row);
  });
  const total = state.lines.length;
  $("lineStats").textContent = total
    ? `${total} dòng · ${okN} đã khớp${badN ? ` · ${badN} chưa` : ""}` : "";
  syncVoiceChips();
}
function editLineText(i, spanEl) {
  const ln = state.lines[i];
  const inp = document.createElement("input");
  inp.type = "text"; inp.className = "ltextedit"; inp.value = ln.text;
  spanEl.replaceWith(inp);
  inp.focus(); inp.select();
  const commit = () => {
    const v = inp.value.trim();
    if (v && v !== ln.text) {
      ln.text = v;
      // sửa chữ: giữ mốc từng từ chỉ khi số từ không đổi
      if (ln.words && ln.words.length !== v.split(/\s+/).filter(Boolean).length)
        ln.words = null;
      scheduleSave();
    }
    renderLineList();
  };
  inp.onblur = commit;
  inp.onkeydown = (e) => {
    if (e.key === "Enter") inp.blur();
    if (e.key === "Escape") { inp.value = ln.text; inp.blur(); }
    e.stopPropagation();
  };
  inp.onclick = (e) => e.stopPropagation();
}
function nudge(i, d) {
  const ln = state.lines[i];
  if (ln.start == null) return;
  ln.start = Math.max(0, Math.min(state.duration || 1e9, ln.start + d));
  if (ln.end != null) ln.end = Math.max(ln.start + 0.05, ln.end + d);
  renderLineList(); scheduleSave(); drawWave();
}
function cycleVoice(i) {
  const ln = state.lines[i];
  ln.voice = ln.voice == null ? "f" : ln.voice === "f" ? "m" : null;
  renderLineList(); scheduleSave();
}
function syncVoiceChips() {
  const ln = state.lines[state.selLine];
  $("btnVoiceF").classList.toggle("on", !!ln && ln.voice === "f");
  $("btnVoiceM").classList.toggle("on", !!ln && ln.voice === "m");
  $("btnVoiceNone").classList.toggle("on", !!ln && !ln.voice);
}
function setVoiceSelected(v) {
  const ln = state.lines[state.selLine];
  if (!ln) return toast("Chưa chọn dòng nào.", true);
  ln.voice = v;
  if (!$("duetChk").checked) {
    $("duetChk").checked = true;
    $("duetBox").hidden = false;
  }
  renderLineList(); scheduleSave(); saveStyle();
}
$("btnVoiceF").addEventListener("click", () => setVoiceSelected("f"));
$("btnVoiceM").addEventListener("click", () => setVoiceSelected("m"));
$("btnVoiceNone").addEventListener("click", () => setVoiceSelected(null));

/* ----- công cụ lời (dán lời / .lrc / AI căn / tách beat / trọn gói) ----- */
const SECTION_RE = /^(lyrics?|verse|chorus|hook|bridge|intro|outro|pre[-\s]?chorus|post[-\s]?chorus|refrain|điệp khúc|lời|phần|đoạn)\b/i;
function cleanLyricLines(arr) {
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
    " — bấm Tự căn nhịp bằng AI hoặc gắn nhịp tay.";
});
$("lrcFile").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const data = await postRaw("/api/lrc", file, {});
    setLines(data.lines, true);
    $("lyricsOk").textContent = `Đã nạp ${data.lines.length} câu có sẵn mốc giờ — khỏi căn nhịp.`;
    toast("Nạp .lrc thành công!");
  } catch (err) { toast(err.message, true); }
});
$("btnAutoAlign").addEventListener("click", async () => {
  if (!state.projectId) return toast("Chưa mở project nào.", true);
  if (!state.lines.length) return toast("Chưa có lời — dán lời trước.", true);
  if (!state.hasSong) return toast("Project chưa có bài hát.", true);
  $("btnAutoAlign").disabled = true;
  try {
    const { job } = await postJSON("/api/auto-align",
      { lines: state.lines.map((l) => l.text) });
    pollJob(job, $("studioProgress"), (res) => {
      $("btnAutoAlign").disabled = false;
      const voices = state.lines.map((l) => l.voice);
      setLines(res.lines, true);
      state.lines.forEach((l, i) => (l.voice = voices[i] || null));
      renderLineList(); scheduleSave();
      const pct = Math.round((res.matched || 0) * 100);
      if (pct >= 50) {
        toast(`AI căn xong (khớp ${pct}% số từ). Câu nào gắn ⚠ thì nghe thử và chỉnh lại.`);
      } else {
        toast(`AI căn xong nhưng chỉ khớp ${pct}% số từ — có thể lời chưa đúng bài. Kiểm tra kỹ từng câu hoặc căn tay.`, true);
      }
    }, (e) => { $("btnAutoAlign").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoAlign").disabled = false;
    toast(err.message, true);
  }
});
$("btnSeparate").addEventListener("click", async () => {
  if (!state.projectId) return toast("Chưa mở project nào.", true);
  if (!state.hasSong) return toast("Project chưa có bài hát.", true);
  $("btnSeparate").disabled = true;
  try {
    const { job } = await postJSON(`/api/projects/${state.projectId}/separate`,
      { mode: sepMode() });
    pollJob(job, $("studioProgress"), () => {
      state.instReady = true;
      $("dlBeat").hidden = false;
      audio().src = bust("/api/audio/inst");
      $("btnSeparate").disabled = false;
      toast(sepMode() === "ai" ? "Tách beat AI xong!" : "Tách beat nhanh xong!");
    }, (e) => { $("btnSeparate").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnSeparate").disabled = false;
    toast(err.message, true);
  }
});
$("btnAutoAll").addEventListener("click", async () => {
  if (!state.projectId) return toast("Chưa mở project nào.", true);
  if (!state.hasSong) return toast("Project chưa có bài hát.", true);
  $("btnAutoAll").disabled = true;
  try {
    const { job } = await postJSON("/api/auto-all", {
      lyrics: state.lines.length ? state.lines.map((l) => l.text) : null,
      sep_mode: sepMode(), style: styleForRender(),
      title: $("songTitle").value.trim(),
      guide: Number($("guide").value), bg: currentBg(),
    });
    pollJob(job, $("studioProgress"), (res) => {
      $("btnAutoAll").disabled = false;
      state.instReady = true;
      $("dlBeat").hidden = false;
      setLines(res.lines, true);
      $("studioOk").textContent = res.source === "ai"
        ? `Xong trọn gói! AI tự chép & căn ${res.count} câu, video đã xuất — sang màn Xuất để xuất lại theo preset, hoặc mở Thư viện xem bài.`
        : `Xong trọn gói! Khớp ${Math.round((res.matched || 0) * 100)}% số từ, ${res.count} câu.`;
      toast("Làm tự động trọn gói xong! 🎉");
    }, (e) => { $("btnAutoAll").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoAll").disabled = false;
    toast(err.message, true);
  }
});

/* ----- phát thử + gắn nhịp tay ----- */
function audioSrc() { return state.instReady ? "/api/audio/inst" : "/api/audio/song"; }
function ensureAudioSrc() {
  const a = audio();
  if (!a.src || !a.src.includes(audioSrc())) a.src = bust(audioSrc());
}
$("btnPlay").addEventListener("click", async () => {
  if (!state.hasSong) return toast("Project chưa có bài hát.", true);
  const a = audio();
  ensureAudioSrc();
  if (a.paused) { try { await a.play(); } catch (e) { toast("Không phát được nhạc: " + e.message, true); } }
  else a.pause();
});
$("btnListen").addEventListener("click", () => $("btnPlay").click());
audio().addEventListener("play", () => ($("btnPlay").textContent = "⏸"));
audio().addEventListener("pause", () => ($("btnPlay").textContent = "▶"));
audio().addEventListener("timeupdate", () => {
  const a = audio();
  $("transportTime").textContent = `${fmt(a.currentTime)} / ${fmt(state.duration)}`;
  updatePreview();
  drawWave();
});
audio().addEventListener("ended", () => {
  if (state.tapping) stopTapping();
});
$("btnSeekBack").addEventListener("click", () => (audio().currentTime = Math.max(0, audio().currentTime - 5)));
$("btnSeekFwd").addEventListener("click", () => (audio().currentTime = Math.min(state.duration || 0, audio().currentTime + 5)));
$("btnPrevLine").addEventListener("click", () => seekLine(-1));
$("btnNextLine").addEventListener("click", () => seekLine(1));
function currentLineIdx(t) {
  let idx = -1;
  state.lines.forEach((l, i) => { if (l.start != null && l.start <= t) idx = i; });
  return idx;
}
function seekLine(d) {
  const a = audio();
  const idx = currentLineIdx(a.currentTime);
  const target = Math.max(0, Math.min(state.lines.length - 1, (idx < 0 ? 0 : idx) + d));
  const ln = state.lines[target];
  if (ln && ln.start != null) {
    a.currentTime = ln.start;
    state.selLine = target;
    renderLineList();
    updatePreview();
  }
}
function updateTapStatus() {
  const done = state.lines.filter((l) => l.start != null).length;
  $("tapStatus").textContent = `Đã căn ${done}/${state.lines.length} câu`;
  const chip = $("tapChip");
  if (state.tapping) {
    chip.textContent = "Chế độ gắn nhịp: BẬT — bấm Space ở đầu mỗi dòng";
    chip.classList.remove("off");
  } else {
    chip.textContent = "Chế độ gắn nhịp: TẮT — bấm nút Gắn nhịp bên dưới để bật";
    chip.classList.add("off");
  }
  $("btnTapUndo").disabled = state.tapIndex === 0;
  $("btnTapRestart").disabled = !state.lines.length;
}
function stopTapping() {
  state.tapping = false;
  audio().pause();
  $("btnTap").textContent = "▶ Phát & gắn nhịp";
  renderLineList(); updateTapStatus();
}
$("btnTap").addEventListener("click", async () => {
  if (!state.lines.length) return toast("Chưa có lời — thêm lời trước.", true);
  if (!state.hasSong) return toast("Project chưa có bài hát.", true);
  if (!state.tapping) {
    ensureAudioSrc();
    state.tapping = true;
    $("btnTap").textContent = "⏺ Đang gắn — bấm khi câu bắt đầu (Space)";
    renderLineList(); updateTapStatus();
    try { await audio().play(); } catch (e) { toast("Không phát được nhạc: " + e.message, true); }
  } else {
    doTap();
  }
});
function doTap() {
  if (!state.tapping || state.tapIndex >= state.lines.length) return;
  const ln = state.lines[state.tapIndex];
  ln.start = Math.round(audio().currentTime * 100) / 100;
  ln.ok = true;
  state.tapIndex++;
  state.selLine = Math.min(state.tapIndex, state.lines.length - 1);
  if (state.tapIndex >= state.lines.length) stopTapping();
  renderLineList(); updateTapStatus(); scheduleSave(); drawWave();
}
$("btnTapUndo").addEventListener("click", () => {
  if (state.tapIndex <= 0) return;
  state.tapIndex--;
  state.lines[state.tapIndex].start = null;
  renderLineList(); updateTapStatus(); scheduleSave();
});
$("btnTapRestart").addEventListener("click", () => {
  state.lines.forEach((l) => (l.start = null));
  state.tapIndex = 0;
  stopTapping();
  audio().currentTime = 0;
  renderLineList(); updateTapStatus(); scheduleSave(); drawWave();
});
document.addEventListener("keydown", (e) => {
  const tag = (document.activeElement || {}).tagName;
  if (/TEXTAREA|INPUT|SELECT/.test(tag || "")) return;
  if ($("viewStudio").hidden) return;
  if (e.code === "Space" && state.tapping) {
    e.preventDefault(); doTap();
  } else if (e.code === "ArrowDown" || e.code === "ArrowUp") {
    e.preventDefault();
    const d = e.code === "ArrowDown" ? 1 : -1;
    state.selLine = Math.max(0, Math.min(state.lines.length - 1, state.selLine + d));
    renderLineList(); syncVoiceChips();
    const ln = state.lines[state.selLine];
    if (ln && ln.start != null) audio().currentTime = ln.start;
  }
});

/* ----- xem trước trực tiếp ----- */
const PV_WORDS = ["Ngày", "mai", "em", "đi", "biển", "nhớ", "tên", "em", "gọi", "về"];
const PV_NEXT = "Sóng hát lời ca ru êm đềm chiều nay";
function updatePreview() { pvRender(audio() ? audio().currentTime || 0 : 0); }
function pvRender(t) {
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
    box.style.background = gradCss(state.gradKind);
    box.style.filter = "";
    $("pvTag").textContent = bg.type === "gradient_anim" ? "Nền động" : "";
  } else if (bg.type === "color") {
    box.style.background = "#0b0e1a"; box.style.filter = "";
    $("pvTag").textContent = "";
  } else {
    box.style.background = "#232a45";
    box.style.filter = Number($("bgBlur").value) > 0
      ? `blur(${Math.round(Number($("bgBlur").value) / 12)}px)` : "";
    $("pvTag").textContent = bg.type === "image" ? "Nền: ảnh của bạn" : "Nền: video của bạn";
  }
  if (bg.type === "gradient" || bg.type === "gradient_anim") {
    const bl = Number($("bgBlur").value);
    box.style.filter = bl > 0 ? `blur(${Math.round(bl / 12)}px)` : "";
  }
  $("pvRatioBadge").textContent = "XEM TRƯỚC · " + st.ratio;
  $("pvTimeBadge").textContent = fmt(t) + " / " + fmt(state.duration);
  $("pvBar").hidden = !st.progress_bar;
  if (st.progress_bar && state.duration > 0)
    $("pvBar").style.width = Math.min(100, t / state.duration * 100) + "%";
  const idx = currentLineIdx(t);
  const lineEl = $("pvLine");
  const scale = (box.clientWidth || 600) / px;
  const fs = Math.max(11, Math.round(Number(st.size) * scale));
  lineEl.style.fontFamily = st.font;
  lineEl.style.fontSize = fs + "px";
  let nextIdx = -1;
  if (idx >= 0 && state.lines[idx]) {
    const ln = state.lines[idx];
    const end = lineEnd(idx);
    const words = ln.text.split(/\s+/).filter(Boolean);
    let sungN;
    if (ln.words && ln.words.length === words.length) {
      sungN = ln.words.filter((w) => t >= w[1]).length;
      var curW = ln.words.findIndex((w) => t >= w[0] && t < w[1]);
    } else {
      const frac = end > ln.start ? Math.max(0, Math.min(1, (t - ln.start) / (end - ln.start))) : 0;
      sungN = Math.round(frac * words.length);
      var curW = Math.min(words.length - 1, Math.floor(frac * words.length));
    }
    lineEl.innerHTML = words.map((w, i) => {
      const col = i < sungN ? st.color : st.base_color;
      const cls = st.effect === "zoom" && i === curW && t >= ln.start ? ' class="cur"' : "";
      return `<span${cls} style="color:${col}">${escHtml(w)}</span>`;
    }).join(" ");
    nextIdx = idx + 1;
  } else {
    const sungN = 4;
    lineEl.innerHTML = PV_WORDS.map((w, i) => {
      const col = i < sungN ? st.color : st.base_color;
      const cls = st.effect === "zoom" && i === sungN - 1 ? ' class="cur"' : "";
      return `<span${cls} style="color:${col}">${w}</span>`;
    }).join(" ");
    nextIdx = -2; // dùng câu mẫu
  }
  const nxt = $("pvNext");
  nxt.style.display = st.two_line ? "" : "none";
  nxt.style.fontFamily = st.font;
  nxt.style.fontSize = Math.max(9, Math.round(fs * 0.62)) + "px";
  if (st.two_line) {
    let ntext = PV_NEXT, ncol = st.base_color;
    if (nextIdx >= 0 && state.lines[nextIdx]) {
      const nl = state.lines[nextIdx];
      ntext = nl.text;
      if (st.duet_color) {
        if (nl.voice === "m") ncol = st.duet_male_color || st.duet_color;
        else if (nl.voice === "f") ncol = st.color;
        else if (nextIdx % 2 === 1) ncol = st.duet_color;
      }
    }
    nxt.innerHTML = ntext.split(/\s+/).filter(Boolean).map((w) =>
      `<span style="color:${ncol}">${escHtml(w)}</span>`).join(" ");
  }
  // chấm đếm ngược: câu kế bắt đầu sau quãng nghỉ >= 1,6s và còn <= 1,5s nữa
  let dots = false;
  if (st.countdown) {
    const nx = state.lines.find((l) => l.start != null && l.start > t);
    if (nx) {
      const prevEnd = idx >= 0 ? lineEnd(idx) : 0;
      if (nx.start - prevEnd >= 1.6 && nx.start - t <= 1.5) dots = true;
    }
  }
  $("pvDots").hidden = !dots;
}
window.addEventListener("resize", () => { updatePreview(); drawWave(); });

async function uploadBg(file, kind) {
  const data = await postRaw("/api/upload-bg-" + kind, file,
    { "X-File-Name": encodeURIComponent(file.name) });
  $("bgOk").textContent = "Đã tải " + (kind === "image" ? "ảnh" : "video") + " nền: " + data.name;
  $("bgTypeSel").value = kind;
  updatePreview(); scheduleSave();
}
$("bgImageFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "image").catch((err) => toast(err.message, true)));
$("bgVideoFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "video").catch((err) => toast(err.message, true)));

/* ----- waveform ----- */
let peaksData = null;
async function loadPeaks() {
  peaksData = null;
  if (!state.projectId || !state.hasSong) { drawWave(); return; }
  try {
    peaksData = await getJSON(`/api/projects/${state.projectId}/peaks?src=song&n=280`);
  } catch (e) { peaksData = null; }
  drawWave();
}
function sectionsOf() {
  const secs = [];
  let prevEnd = 0;
  state.lines.forEach((l, i) => {
    if (l.start == null) return;
    if (secs.length === 0 || l.start - prevEnd >= 3.0)
      secs.push({ at: l.start, n: secs.length + 1 });
    prevEnd = Math.max(prevEnd, lineEnd(i));
  });
  return secs;
}
function drawWave() {
  const cv = $("waveCanvas");
  if (!cv || $("viewStudio").hidden) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 86;
  if (!W) return;
  if (cv.width !== Math.round(W * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const dur = (peaksData && peaksData.duration) || state.duration || 0;
  const peaks = peaksData && peaksData.peaks;
  if (!peaks || !peaks.length || !dur) {
    g.fillStyle = "#6b6b82";
    g.font = "13px 'Segoe UI', Arial";
    g.textAlign = "center";
    g.fillText(state.hasSong ? "Đang tải sóng âm…" : "Chưa có bài hát", W / 2, H / 2 + 4);
    return;
  }
  const t = audio().currentTime || 0;
  const playedFrac = Math.max(0, Math.min(1, t / dur));
  const n = peaks.length;
  const bw = W / n;
  const grad = g.createLinearGradient(0, 0, W, 0);
  grad.addColorStop(0, "#ff4d7e"); grad.addColorStop(1, "#8b5cf6");
  const topPad = 20, botH = H - topPad - 6;
  for (let i = 0; i < n; i++) {
    const h = Math.max(2, peaks[i] * botH);
    const x = i * bw;
    g.fillStyle = i / n <= playedFrac ? grad : "#34344e";
    g.beginPath();
    g.roundRect(x + 0.5, topPad + (botH - h) / 2, Math.max(1, bw - 1.5), h, 2);
    g.fill();
  }
  // mốc đoạn D1..Dn tại điểm bắt đầu các đoạn (nghỉ >= 3s giữa hai câu)
  const secs = sectionsOf();
  const curSec = secs.filter((s) => s.at <= t).length;
  secs.forEach((s, i) => {
    const x = Math.max(2, Math.min(W - 30, s.at / dur * W));
    g.fillStyle = i + 1 === curSec ? "#ff4d7e" : "#2fbf71";
    g.beginPath();
    g.roundRect(x, 2, 26, 15, 5);
    g.fill();
    g.fillStyle = "#fff";
    g.font = "bold 10px 'Segoe UI', Arial";
    g.textAlign = "center";
    g.fillText("D" + s.n, x + 13, 13);
  });
  // đường chạy
  const px = playedFrac * W;
  g.fillStyle = "#ff4d7e";
  g.fillRect(px - 1, 0, 2, H);
}
$("waveCanvas").addEventListener("click", (e) => {
  if (!peaksData || !peaksData.duration || !state.hasSong) return;
  const r = $("waveCanvas").getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  audio().currentTime = frac * peaksData.duration;
  updatePreview(); drawWave();
});

/* ================= XUẤT VIDEO ================= */
const EX_FORMATS = {
  yt: [1920, 1080], shorts: [1080, 1920], fb: [1080, 1080], yt4k: [3840, 2160],
};
const EX_KBPS = { cao: 16000, vua: 10000, thap: 6000 };
const exState = { format: "yt", info: null, payload: null, filenameDirty: false, queueTimer: null };
function currentExportConfig() {
  return {
    format: exState.format,
    encoder: $("exEncoder").value,
    quality: $("exQuality").value,
    burn: $("exBurn").checked,
    export_ass: $("exAss").checked,
    out_dir: $("exOutDir").value.trim(),
    filename: $("exFilename").value.trim().replace(/\.mp4$/i, ""),
  };
}
async function openExport() {
  if (!state.projectId) return toast("Chưa mở project nào.", true);
  await flushSave();
  try {
    exState.payload = await getJSON("/api/project/current");
    if (!exState.info) exState.info = await getJSON("/api/export/info");
    const info = exState.info;
    const badge = $("exNvencBadge");
    if (info.nvenc) {
      badge.hidden = false;
      badge.textContent = "✓ NVENC" + (info.gpu ? " · " + info.gpu.replace(/^NVIDIA GeForce /, "") : "");
    } else {
      badge.hidden = false;
      badge.textContent = "CPU";
      badge.style.background = "#23232f"; badge.style.color = "var(--mut)";
    }
    if (!$("exOutDir").value) $("exOutDir").value = info.save_dir || "";
    const p = exState.payload;
    $("exTitle").textContent = "· " + p.project.title;
    $("exThumb").style.background = gradCss(p.project.grad || gradForTitle(p.project.title));
    const first = (p.lines || []).find((l) => l.text);
    $("exThumbLine").textContent = first ? first.text : p.project.title;
    exState.filenameDirty = false;
    suggestFilename();
    updateExInfo();
    showView("export");
    startQueuePoll();
  } catch (err) { toast(err.message, true); }
}
function suggestFilename() {
  if (exState.filenameDirty || !exState.payload) return;
  const [w, h] = EX_FORMATS[exState.format];
  const res = Math.min(w, h) + "p";
  $("exFilename").value = `${exState.payload.project.title} — Karaoke ${res}.mp4`;
}
function updateExInfo() {
  const p = exState.payload;
  if (!p) return;
  const dur = p.duration || 0;
  $("exDur").textContent = fmt(dur);
  $("exSrc").textContent = !p.inst_ready ? "Nhạc gốc (chưa tách beat)"
    : p.project.inst_mode === "ai" ? "Beat đã tách (AI)" : "Beat cắt nhanh";
  const lines = p.lines || [];
  const allOk = lines.length > 0 && lines.every((l) => l.ok !== false);
  $("exLines").textContent = lines.length
    ? `${lines.length} dòng · ${allOk ? "khớp từng chữ" : "có dòng chưa khớp hẳn"}` : "Chưa có lời";
  const kb = EX_KBPS[$("exQuality").value] || 16000;
  const mb = (kb + 192) * dur / 8 / 1024;
  $("exSize").textContent = dur ? `~${Math.max(1, Math.round(mb))} MB` : "—";
  const encSel = $("exEncoder").value;
  const useNv = encSel === "nvenc" || (encSel === "auto" && exState.info && exState.info.nvenc);
  let factor = useNv ? 0.35 : 0.95;
  if (exState.format === "yt4k") factor *= 2.2;
  const eta = dur * factor;
  $("exEta").textContent = dur
    ? "~" + (eta >= 60 ? `${Math.floor(eta / 60)} phút ${Math.round(eta % 60)} giây` : `${Math.max(2, Math.round(eta))} giây`)
    : "—";
  suggestFilename();
}
$("fmtGrid").addEventListener("click", (e) => {
  const b = e.target.closest(".fmtcard");
  if (!b) return;
  exState.format = b.dataset.format;
  document.querySelectorAll(".fmtcard").forEach((x) =>
    x.classList.toggle("active", x === b));
  updateExInfo();
});
["exEncoder", "exQuality"].forEach((id) => $(id).addEventListener("change", updateExInfo));
$("exFilename").addEventListener("input", () => (exState.filenameDirty = true));
$("btnAddQueue").addEventListener("click", async () => {
  if (!state.projectId) return;
  await flushSave();
  $("btnAddQueue").disabled = true;
  try {
    await postJSON("/api/export/queue",
      { project_id: state.projectId, config: currentExportConfig() });
    toast("Đã thêm vào hàng đợi xuất.");
    startQueuePoll();
    refreshQueueBadge();
  } catch (err) { toast(err.message, true); }
  $("btnAddQueue").disabled = false;
});
function renderQueue(items) {
  const box = $("exQueueList");
  if (!items.length) {
    box.innerHTML = '<p class="hint">Chưa có bài nào trong hàng đợi.</p>';
  } else {
    box.innerHTML = items.map((it) => {
      let right, cls = "";
      if (it.status === "done") { right = '<span class="qpct done">✓ Xong</span>'; cls = " done"; }
      else if (it.status === "error") right = '<span class="qpct" style="color:var(--err)">✗ Lỗi</span>';
      else if (it.status === "running") right = `<span class="qpct">${Math.round(it.progress)}%</span>`;
      else right = '<span class="qpct" style="color:var(--mut)">Chờ</span>';
      let sub = escHtml(it.format || "");
      if (it.status === "running")
        sub = `Đang render${it.encoder ? " · " + (it.encoder === "nvenc" ? "NVENC" : "CPU") : ""} · ${escHtml(it.label || "")}`;
      else if (it.status === "done")
        sub = `Đã lưu · ${fmtBytes(it.size_bytes)} · ${escHtml((it.saved_path || "").split(/[\\/]/).pop())}`;
      else if (it.status === "error")
        sub = escHtml(it.error || "Lỗi");
      return `<div class="qitem${cls}">
        <div class="qhead"><span class="qname">${escHtml(it.title)}</span>${right}</div>
        <div class="qsub">${sub}</div>
        <div class="qbar"><div style="width:${it.progress || 0}%"></div></div>
        ${it.status !== "running" ? `<button class="qrm" data-qrm="${it.id}" title="Gỡ khỏi hàng đợi">✕ gỡ</button>` : ""}
      </div>`;
    }).join("");
  }
  const active = items.filter((i) => i.status === "queued" || i.status === "running").length;
  $("exQueueFoot").textContent = items.length
    ? `Tổng ${items.length} bài${active ? ` · ${active} đang chờ/xuất` : ""}` : "";
  box.querySelectorAll("[data-qrm]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await postJSON(`/api/export/queue/${b.dataset.qrm}/remove`, {});
        pollQueueOnce();
      } catch (err) { toast(err.message, true); }
    }));
}
async function pollQueueOnce() {
  try {
    const data = await getJSON("/api/export/queue");
    renderQueue(data.items || []);
    const active = (data.items || []).some(
      (i) => i.status === "queued" || i.status === "running");
    if (!active && exState.queueTimer) {
      clearInterval(exState.queueTimer);
      exState.queueTimer = null;
      loadLibrary();
    }
    return active;
  } catch (e) { return true; }
}
function startQueuePoll() {
  pollQueueOnce();
  if (exState.queueTimer) clearInterval(exState.queueTimer);
  exState.queueTimer = setInterval(pollQueueOnce, 2000);
}
async function refreshQueueBadge() {
  try {
    const data = await getJSON("/api/export/queue");
    const active = (data.items || []).filter(
      (i) => i.status === "queued" || i.status === "running").length;
    $("navQueueCount").hidden = !active;
    $("navQueueCount").textContent = active;
  } catch (e) { /* chưa cần badge khi server bận */ }
}

/* ----- mẫu cấu hình (preset) ----- */
let presetItems = [];
async function loadPresets() {
  try {
    const data = await getJSON("/api/presets");
    presetItems = data.items || [];
    const sel = $("presetApplySel");
    sel.innerHTML = '<option value="">Áp mẫu đã lưu…</option>' +
      presetItems.map((p) => `<option value="${escHtml(p.name)}">${escHtml(p.name)}</option>`).join("");
  } catch (e) { /* preset là phụ — lỗi thì bỏ qua */ }
}
$("presetApplySel").addEventListener("change", () => {
  const name = $("presetApplySel").value;
  if (!name) return;
  const p = presetItems.find((x) => x.name === name);
  if (!p) return;
  if (p.style) applyStyleToControls(p.style, p.bg, null);
  const ex = p.export || {};
  if (ex.format && EX_FORMATS[ex.format]) {
    exState.format = ex.format;
    document.querySelectorAll(".fmtcard").forEach((x) =>
      x.classList.toggle("active", x.dataset.format === ex.format));
  }
  if (ex.encoder) $("exEncoder").value = ex.encoder;
  if (ex.quality) $("exQuality").value = ex.quality;
  if (ex.burn != null) $("exBurn").checked = !!ex.burn;
  if (ex.export_ass != null) $("exAss").checked = !!ex.export_ass;
  if (ex.out_dir) $("exOutDir").value = ex.out_dir;
  exState.filenameDirty = false;
  updateExInfo();
  toast("Đã áp mẫu: " + name);
});
$("btnSavePreset").addEventListener("click", async () => {
  await flushSave();
  const name = (window.prompt("Đặt tên cho mẫu cấu hình (phong cách + cấu hình xuất):") || "").trim();
  if (!name) return;
  try {
    const data = await postJSON("/api/presets", {
      name, style: collectStyle(), bg: currentBg(),
      export: currentExportConfig(),
    });
    presetItems = data.items || presetItems;
    loadPresets();
    toast("Đã lưu mẫu: " + name);
  } catch (err) { toast(err.message, true); }
});

/* ================= CÀI ĐẶT ================= */
async function openSettings() {
  showView("settings");
  try {
    const info = await getJSON("/api/app-info");
    $("setVersion").textContent = "v" + info.version;
    $("setSaveDir").textContent = info.save_dir;
  } catch (e) { /* bỏ qua */ }
  const st = state.storage;
  if (st) $("setStorage").textContent = `${fmtBytes(st.projects_bytes || 0)} / ${fmtBytes(st.total || 0)}`;
}
$("btnOpenFolder").addEventListener("click", async () => {
  try { await postJSON("/api/open-folder", {}); }
  catch (err) { toast(err.message, true); }
});

/* ================= KHỞI TẠO ================= */
restoreStyle();
syncSepRadios();
loadLibrary();
loadPresets();
showView("library");
