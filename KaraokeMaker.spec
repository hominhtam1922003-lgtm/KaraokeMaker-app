# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec cho Karaoke Maker (onefile).

CI Windows chuẩn bị trước khi build:
- ffmpeg.exe + ffprobe.exe đặt ở thư mục gốc project (tải từ BtbN FFmpeg-Builds)
- models/UVR-MDX-NET-Inst_HQ_3.onnx (tải từ TRvlvr/model_repo)
"""
import os

from PyInstaller.utils.hooks import collect_all

ort_datas, ort_binaries, ort_hidden = collect_all("onnxruntime")


def _collect(name):
    """collect_all an toàn: thiếu thư viện thì trả rỗng (build local thiếu
    faster-whisper vẫn đóng gói được bản không có tự căn AI)."""
    try:
        return collect_all(name)
    except Exception:
        return [], [], []


fw_datas, fw_binaries, fw_hidden = _collect("faster_whisper")
ct_datas, ct_binaries, ct_hidden = _collect("ctranslate2")
tk_datas, tk_binaries, tk_hidden = _collect("tokenizers")
av_datas, av_binaries, av_hidden = _collect("av")
yd_datas, yd_binaries, yd_hidden = _collect("yt_dlp")
wv_datas, wv_binaries, wv_hidden = _collect("webview")

binaries = (list(ort_binaries) + list(fw_binaries) + list(ct_binaries)
            + list(tk_binaries) + list(av_binaries) + list(yd_binaries)
            + list(wv_binaries))
for cand in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
    if os.path.exists(cand):
        binaries.append((cand, "."))

datas = ([("web", "web")] + list(ort_datas) + list(fw_datas)
         + list(ct_datas) + list(tk_datas) + list(av_datas) + list(yd_datas)
         + list(wv_datas))
if os.path.exists(os.path.join("models", "UVR-MDX-NET-Inst_HQ_3.onnx")):
    datas.append(("models/UVR-MDX-NET-Inst_HQ_3.onnx", "models"))

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=(ort_hidden + fw_hidden + ct_hidden + tk_hidden + av_hidden
                   + yd_hidden + wv_hidden
                   + ["karaoke.lyrics", "karaoke.media", "karaoke.mdx",
                      "karaoke.align", "karaoke.ytdl",
                      "karaoke.whisper_worker"]),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KaraokeMaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
