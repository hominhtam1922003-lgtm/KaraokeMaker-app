"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  duration: 0, instReady: false, lines: [], tapped: false,
  tapIndex: 0, tapping: false, color: "#FFD400",
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
    unlock("step2"); unlock("step3");
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
  state.lines = lines.map((l) => ({ text: l.text, start: withTimes ? l.start : null }));
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
$("btnUseLyrics").addEventListener("click", () => {
  const raw = $("lyricsText").value.split("\n").map((s) => s.trim()).filter(Boolean);
  if (!raw.length) return toast("Chưa có dòng lời nào.", true);
  setLines(raw.map((text) => ({ text })), false);
  $("lyricsOk").textContent = `Đã nhận ${raw.length} câu — xuống bước 4 căn nhịp.`;
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

/* ---------- Bước 6: xuất video ---------- */
$("btnRender").addEventListener("click", async () => {
  const missing = state.lines.filter((l) => l.start == null).length;
  if (missing) return toast(`Còn ${missing} câu chưa căn nhịp.`, true);
  const bgType = document.querySelector('input[name="bgtype"]:checked').value;
  $("btnRender").disabled = true;
  try {
    const { job } = await postJSON("/api/render", {
      lines: state.lines.map((l) => ({ start: l.start, text: l.text })),
      style: { color: state.color, size: Number($("fontSize").value) },
      guide: Number($("guide").value),
      bg: { type: bgType, value: "#0b0e1a" },
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
