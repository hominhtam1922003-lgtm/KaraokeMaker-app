# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec cho Karaoke Maker (onefile).

CI Windows chuẩn bị trước khi build:
- ffmpeg.exe + ffprobe.exe đặt ở thư mục gốc project (tải từ BtbN FFmpeg-Builds)
- models/UVR-MDX-NET-Inst_HQ_3.onnx (tải từ TRvlvr/model_repo)
"""
import os

from PyInstaller.utils.hooks import collect_all

ort_datas, ort_binaries, ort_hidden = collect_all("onnxruntime")

binaries = list(ort_binaries)
for cand in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
    if os.path.exists(cand):
        binaries.append((cand, "."))

datas = [("web", "web")] + list(ort_datas)
if os.path.exists(os.path.join("models", "UVR-MDX-NET-Inst_HQ_3.onnx")):
    datas.append(("models/UVR-MDX-NET-Inst_HQ_3.onnx", "models"))

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=ort_hidden + ["karaoke.lyrics", "karaoke.media", "karaoke.mdx"],
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
