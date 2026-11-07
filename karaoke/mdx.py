"""Tách beat bằng model MDX-Net (ONNX) — UVR-MDX-NET-Inst_HQ_3.

Pipeline: STFT (n_fft=6144, hop=1024) -> cắt phổ thành các đoạn 256 khung,
chạy model, ghép chồng lấp -> iSTFT ra nhạc cụ (instrumental).
Thứ tự 4 kênh đầu vào được kiểm chứng bằng bài test tổng hợp trong tools/.
"""
import os
import sys

import numpy as np

SR = 44100
N_FFT = 6144  # giá trị đúng được chốt bằng tools/test_song.py (6144 hay 7680)
HOP = 1024
DIM_F = 3072
DIM_T = 256
CHUNK_STEP = 192  # chồng lấp 64 khung giữa các đoạn


def _hann_periodic(n):
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)


def stft(x, n_fft=N_FFT, hop=HOP):
    """x: (samples,) float32 -> complex64 (bins, frames), khớp torch.stft(center=True)."""
    win = _hann_periodic(n_fft).astype(np.float32)
    pad = n_fft // 2
    xp = np.pad(x, pad, mode="reflect")
    n_frames = 1 + (len(xp) - n_fft) // hop
    strides = (xp.strides[0] * hop, xp.strides[0])
    frames = np.lib.stride_tricks.as_strided(xp, shape=(n_frames, n_fft),
                                             strides=strides)
    spec = np.fft.rfft(frames * win, axis=1)
    return spec.T.astype(np.complex64)  # (bins, frames)


def istft(spec, n_fft=N_FFT, hop=HOP, length=None):
    """spec: (bins, frames) complex -> (samples,) float32."""
    win = _hann_periodic(n_fft).astype(np.float32)
    n_frames = spec.shape[1]
    frames = np.fft.irfft(spec.T, n=n_fft, axis=1) * win
    out_len = n_fft + hop * (n_frames - 1)
    out = np.zeros(out_len, dtype=np.float32)
    wsum = np.zeros(out_len, dtype=np.float32)
    w2 = (win * win).astype(np.float32)
    for i in range(n_frames):
        s = i * hop
        out[s:s + n_fft] += frames[i]
        wsum[s:s + n_fft] += w2
    nz = wsum > 1e-10
    out[nz] /= wsum[nz]
    pad = n_fft // 2
    out = out[pad:out_len - pad]
    if length is not None:
        out = out[:length] if len(out) >= length else np.pad(out, (0, length - len(out)))
    return out.astype(np.float32)


def _to_model_input(spec2, order="A"):
    """spec2: (2, DIM_F, T) complex (L, R) -> (4, DIM_F, T) float32."""
    re_l, im_l = spec2[0].real, spec2[0].imag
    re_r, im_r = spec2[1].real, spec2[1].imag
    if order == "A":
        chans = (re_l, im_l, re_r, im_r)
    else:  # "B"
        chans = (re_l, re_r, im_l, im_r)
    return np.stack(chans).astype(np.float32)


def _from_model_output(arr, order="A"):
    """(4, DIM_F, T) float32 -> (2, DIM_F, T) complex."""
    if order == "A":
        re_l, im_l, re_r, im_r = arr[0], arr[1], arr[2], arr[3]
    else:
        re_l, re_r, im_l, im_r = arr[0], arr[1], arr[2], arr[3]
    out = np.empty((2, arr.shape[1], arr.shape[2]), dtype=np.complex64)
    out[0] = re_l + 1j * im_l
    out[1] = re_r + 1j * im_r
    return out


def default_model_path():
    names = ["UVR-MDX-NET-Inst_HQ_3.onnx"]
    roots = []
    if getattr(sys, "frozen", False):
        roots += [os.path.join(sys._MEIPASS, "models"),
                  os.path.join(os.path.dirname(sys.executable), "models")]
    roots.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"))
    for root in roots:
        for n in names:
            p = os.path.join(root, n)
            if os.path.exists(p):
                return p
    return os.path.join(roots[-1], names[0])


def load_wav_f32(path):
    """Đọc WAV s16 stereo 44.1k (định dạng làm việc) -> float32 (2, samples) [-1,1]."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            n = w.getnframes()
            ch, sw, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(n)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Không đọc được file WAV làm việc: {e}") from e
    if n == 0:
        raise ValueError("File nhạc rỗng (0 mẫu âm thanh)")
    if sw != 2 or sr != SR:
        raise ValueError("WAV đầu vào phải là s16/44.1kHz (dùng media.extract_audio trước)")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch == 1:
        data = np.stack([data, data])
    else:
        data = data.reshape(-1, ch).T[:2]
    return data


def save_wav_f32(path, data):
    """data: (2, samples) float32 -> WAV s16."""
    import wave
    x = np.clip(data, -1.0, 1.0)
    inter = (x.T.reshape(-1) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(inter.tobytes())


def separate_mdx(in_wav, out_wav, model_path=None, progress_cb=None, order="A",
                 n_fft=None, vocal_out=None):
    """Tách instrumental từ in_wav, ghi ra out_wav. progress_cb(pct, label).
    Nếu có vocal_out: ghi thêm stem GIỌNG HÁT = bản gốc trừ instrumental
    (cách suy stem phụ chuẩn của UVR) — dùng để AI chép lời trên giọng đã
    tách, nghe rõ chữ hơn hẳn so với chép trên bản phối đầy nhạc."""
    import onnxruntime as ort

    n_fft = int(n_fft or N_FFT)
    model_path = model_path or default_model_path()
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Không thấy model AI: {model_path}")
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name

    audio = load_wav_f32(in_wav)  # (2, N)
    # Chuẩn hoá đỉnh như implementation tham chiếu (audio-separator): >0.9 thì
    # kéo về 0.9 trước khi chạy model, nhân trả lại đỉnh gốc sau khi tách.
    peak = float(np.abs(audio).max()) or 1.0
    scale = 0.9 / peak if peak > 0.9 else 1.0
    audio = audio * scale
    n_samples = audio.shape[1]
    n_bins = n_fft // 2 + 1
    specs = np.stack([stft(audio[0], n_fft=n_fft), stft(audio[1], n_fft=n_fft)])
    specs[:, :3, :] = 0  # tham chiếu cũng zero 3 bin thấp nhất trước khi chạy model
    specs = specs[:, :DIM_F, :]
    total_t = specs.shape[2]

    acc = np.zeros_like(specs)
    weight = np.zeros(total_t, dtype=np.float32)
    win_t = _hann_periodic(DIM_T).astype(np.float32)

    starts = list(range(0, max(1, total_t - DIM_T + 1), CHUNK_STEP))
    if not starts or starts[-1] + DIM_T < total_t:
        starts.append(max(0, total_t - DIM_T))
    starts = sorted(set(starts))

    for idx, s in enumerate(starts):
        chunk = specs[:, :, s:s + DIM_T]
        if chunk.shape[2] < DIM_T:
            chunk = np.pad(chunk, ((0, 0), (0, 0), (0, DIM_T - chunk.shape[2])))
        x = _to_model_input(chunk, order)[None, ...]
        y = sess.run(None, {in_name: x})[0][0]
        est = _from_model_output(y, order)
        # Đoạn cuối (hoặc file ngắn hơn một đoạn 256 khung): model luôn trả
        # đủ 256 khung do padding — chỉ cộng phần khung thật vào bộ tích lũy.
        valid = min(DIM_T, total_t - s)
        acc[:, :, s:s + valid] += est[:, :, :valid] * win_t[None, None, :valid]
        weight[s:s + valid] += win_t[:valid]
        if progress_cb:
            progress_cb((idx + 1) / len(starts) * 100.0, "tách beat AI")
    w = np.maximum(weight, 1e-8)
    acc = acc / w[None, None, :]

    pad_bins = n_bins - DIM_F
    full = np.concatenate(
        [acc, np.zeros((2, pad_bins, total_t), dtype=np.complex64)], axis=1)
    outs = [istft(full[ch], n_fft=n_fft, length=n_samples) / scale for ch in range(2)]
    inst = np.stack(outs)
    save_wav_f32(out_wav, inst)
    if vocal_out:
        vocal = np.clip(audio / scale - inst, -1.0, 1.0)
        save_wav_f32(vocal_out, vocal.astype(np.float32))
    if progress_cb:
        progress_cb(100.0, "tách beat AI")
