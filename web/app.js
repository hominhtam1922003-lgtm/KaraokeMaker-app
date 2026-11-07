"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  duration: 0, instReady: false, lines: [], tapped: false,
  tapIndex: 0, tapping: false, color: "#FFD400", baseColor: "#FFFFFF",
  outlineW: 3, gradKind: "demtim",
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
function unlock(id) { $(id).classList.remove("locked"); }
function bust(url) { return url + "?v=" + Date.now(); }

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
  bar.style.width = "0%"; pct.textContent = "0%";
  const iv = setInterval(async () => {
    try {
      const r = await fetch("/api/job/" + jobId);
      const job = await r.json();
      bar.style.width = job.progress + "%";
      pct.textContent = (job.label ? job.label + " · " : "") + job.progress + "%";
      if (job.status === "done") { clearInterval(iv); onDone && onDone(job.result); }
      else if (job.status === "error") {
        clearInterval(iv); progressEl.hidden = true;
        (onErr || ((e) => toast(e, true)))(job.error || "Lỗi không rõ");
      }
    } catch (e) { /* mạng chập chờn, thử lại ở nhịp sau */ }
  }, 400);
}

/* ---------- Bước 1: bài hát ---------- */
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
    $("btnSeparate").disabled = false;
    state.instReady = false;
    $("instInfo").hidden = true;
    unlock("step2"); unlock("step3"); unlock("stepAuto");
    $("btnAutoAll").disabled = false;
    toast("Đã nạp bài hát. Tách beat ở bước 2 nhé.");
  } catch (err) {
    $("songDropText").textContent = "Bấm để chọn file bài hát";
    toast(err.message, true);
  }
});

/* ---------- Bước 2: tách beat ---------- */
$("btnSeparate").addEventListener("click", async () => {
  const mode = document.querySelector('input[name="sepmode"]:checked').value;
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

/* ---------- Bước 3: lời ---------- */
function setLines(lines, withTimes) {
  state.lines = lines.map((l) => ({
    text: l.text, start: withTimes ? l.start : null, words: l.words || null,
  }));
  state.tapIndex = 0; state.tapping = false; tapAudio.pause();
  $("btnTap").textContent = "▶ Phát & căn nhịp";
  $("btnTapUndo").disabled = true; $("btnTapRestart").disabled = !state.lines.length;
  renderLineList(); updateTapStatus(); unlock("step4");
  if (withTimes) { state.tapped = true; unlock("step5"); unlock("step6"); $("btnRender").disabled = false; }
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
    unlock("step5"); unlock("step6"); $("btnRender").disabled = false;
    toast("Căn nhịp xong! Chỉnh kiểu chữ rồi xuất video thôi.");
  }
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
    " — xuống bước 4 căn nhịp.";
});

/* Tự căn nhịp bằng AI: server nghe bài hát, đối chiếu lời, trả mốc giờ. */
$("btnAutoAlign").addEventListener("click", async () => {
  if (!state.lines.length) return toast("Chưa có lời — làm bước 3 trước.", true);
  if (!state.duration) return toast("Chưa có bài hát — làm bước 1 trước.", true);
  $("btnAutoAlign").disabled = true;
  try {
    const { job } = await postJSON("/api/auto-align",
      { lines: state.lines.map((l) => l.text) });
    pollJob(job, $("alignProgress"), (res) => {
      $("btnAutoAlign").disabled = false;
      setLines(res.lines, true);
      const pct = Math.round((res.matched || 0) * 100);
      if (pct >= 50) {
        toast(`AI căn xong (khớp ${pct}% số từ). Nghe thử — câu nào lệch thì bấm −0,1s/+0,1s ở từng câu để sửa.`);
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
    $("lyricsOk").textContent = `Đã nạp ${data.lines.length} câu có sẵn mốc giờ — khỏi căn nhịp, xuống bước 5.`;
    renderLineList(); updateTapStatus();
    toast("Nạp .lrc thành công!");
  } catch (err) { toast(err.message, true); }
});

/* ---------- Bước 4: căn nhịp ---------- */
function tapSource() { return state.instReady ? "/api/audio/inst" : "/api/audio/song"; }
$("btnTap").addEventListener("click", async () => {
  if (!state.lines.length) return toast("Chưa có lời — làm bước 3 trước.", true);
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

/* ---------- Bước 5: kiểu & nền ---------- */
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
}
PRESETS.forEach((p, i) => {
  const b = document.createElement("button");
  b.className = "preset" + (i === 0 ? " active" : "");
  b.innerHTML = `<span class="dot" style="background:${p.color}"></span>` +
    `<span class="dot" style="background:${p.base}"></span> ${p.name}`;
  b.onclick = () => applyPreset(p, b);
  $("presetGrid").appendChild(b);
});
$("gradRow").addEventListener("click", (e) => {
  const b = e.target.closest(".grad");
  if (!b) return;
  document.querySelectorAll(".grad").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.gradKind = b.dataset.g;
  document.querySelector('input[name="bgtype"][value="gradient"]').checked = true;
});
function collectStyle() {
  return {
    color: state.color, base_color: state.baseColor,
    size: Number($("fontSize").value), font: $("fontSel").value,
    effect: $("effectSel").value, fade: $("fadeChk").checked,
    two_line: $("twoLineChk").checked, outline_w: state.outlineW,
  };
}
function currentBg() {
  const t = document.querySelector('input[name="bgtype"]:checked').value;
  if (t === "gradient") return { type: "gradient", value: state.gradKind };
  return { type: t, value: "#0b0e1a" };
}
$("colorSwatches").addEventListener("click", (e) => {
  const b = e.target.closest(".sw");
  if (!b) return;
  document.querySelectorAll(".sw").forEach((x) => x.classList.remove("active"));
  b.classList.add("active");
  state.color = b.dataset.color;
});
$("fontSize").addEventListener("input", (e) => ($("sizeVal").textContent = e.target.value));
async function uploadBg(file, kind) {
  const data = await postRaw("/api/upload-bg-" + kind, file,
    { "X-File-Name": encodeURIComponent(file.name) });
  $("bgOk").textContent = "Đã tải " + (kind === "image" ? "ảnh" : "video") + " nền: " + data.name;
  document.querySelector(`input[name="bgtype"][value="${kind}"]`).checked = true;
}
$("bgImageFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "image").catch((err) => toast(err.message, true)));
$("bgVideoFile").addEventListener("change", (e) => e.target.files[0] && uploadBg(e.target.files[0], "video").catch((err) => toast(err.message, true)));
$("guide").addEventListener("input", (e) => ($("guideVal").textContent = e.target.value + "%"));

/* ---------- Tự động toàn phần ---------- */
$("btnAutoAll").addEventListener("click", async () => {
  if (!state.duration) return toast("Chưa có bài hát — làm bước 1 trước.", true);
  $("btnAutoAll").disabled = true;
  $("autoOk").textContent = "";
  try {
    const style = collectStyle();
    const { job } = await postJSON("/api/auto-all", {
      lyrics: state.lines.length ? state.lines.map((l) => l.text) : null,
      sep_mode: document.querySelector('input[name="sepmode"]:checked').value,
      style,
      title: $("songTitle").value.trim(),
      guide: Number($("guide").value),
      bg: currentBg(),
    });
    pollJob(job, $("autoProgress"), (res) => {
      $("btnAutoAll").disabled = false;
      state.instReady = true;
      $("instPlayer").src = bust("/api/audio/inst");
      $("instInfo").hidden = false;
      setLines(res.lines, true);
      $("renderDone").hidden = false;
      $("outVideo").src = bust("/api/video");
      unlock("step5"); unlock("step6");
      $("autoOk").textContent = res.source === "ai"
        ? `Xong! AI tự chép & căn ${res.count} câu. Nghe thử — sai chữ ở đâu thì sửa lời ở bước 3 rồi bấm Tự căn bằng AI để làm lại chuẩn hơn.`
        : `Xong! Dùng lời bạn dán, AI khớp ${Math.round((res.matched || 0) * 100)}% số từ, ${res.count} câu.`;
      toast("Video karaoke tự động xong! 🎉");
    }, (e) => { $("btnAutoAll").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnAutoAll").disabled = false;
    toast(err.message, true);
  }
});

/* ---------- Bước 6: xuất video ---------- */
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
      $("outVideo").src = bust("/api/video");
      $("btnRender").disabled = false;
      toast("Xuất video xong! 🎉");
    }, (e) => { $("btnRender").disabled = false; toast(e, true); });
  } catch (err) {
    $("btnRender").disabled = false;
    toast(err.message, true);
  }
});
