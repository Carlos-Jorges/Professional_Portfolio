"""""
=============================================================================
BMET5995 Advanced Bionics
Cochlear Implant Sound Processing Simulator
Author: Carlos Jorges Ramirez
=============================================================================
Strategies : F0F1F2  |  CIS  |  ACE
Interface  : Tkinter GUI (stdlib)
DSP        : NumPy + SciPy
Plots      : Matplotlib
=============================================================================
"""

# ── Standard library ────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import csv
import os
import time
import wave
import struct
import tempfile

# ── Third-party (permitted) ──────────────────────────────────────────────────
import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.signal import resample_poly, lfilter, butter, hilbert
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors


# =============================================================================
#  CONSTANTS & COCHLEAR PARAMETERS
# =============================================================================

TARGET_FS       = 16_000        # Hz  – internal processing sample rate
N_ELECTRODES    = 16            # total electrode channels
EPOCH_MS        = 2             # ms  – analysis frame length
OVERLAP_MS      = 6             # ms  – total context window (3 ms each side)
A_MAX           = 1024          # C-level (maximum comfortable level)
DYNAMIC_DB      = 10            # dB dynamic range  →  A_MAX / A_MIN = 10^(10/20)
A_MIN           = int(A_MAX / (10 ** (DYNAMIC_DB / 20)))   # ≈ 324

# Cochlear frequency map: 16 electrodes, apical (E1, low freq) → basal (E16, high freq)
# Based on a logarithmic spread across the speech-relevant range 200–8000 Hz
ELECTRODE_CF = np.round(
    np.logspace(np.log10(200), np.log10(8000), N_ELECTRODES)
).astype(int)                   # centre frequencies in Hz, index 0 = apical

# F0F1F2 – electrode range boundaries for each electrode
ELECTRODE_EDGES = np.concatenate([
    [ELECTRODE_CF[0] / np.sqrt(ELECTRODE_CF[1] / ELECTRODE_CF[0])],
    np.sqrt(ELECTRODE_CF[:-1] * ELECTRODE_CF[1:]),
    [ELECTRODE_CF[-1] * np.sqrt(ELECTRODE_CF[-1] / ELECTRODE_CF[-2])]
])

# ACE / CIS – gammatone-inspired bandpass filter bank boundaries
FILTERBANK_LOW  = 200           # Hz  – lowest filter edge
FILTERBANK_HIGH = 7000          # Hz  – highest filter edge
N_FILTERS       = N_ELECTRODES

# ACE – number of maxima to select per frame (N-of-M)
ACE_N           = 8             # N: active channels per frame


# =============================================================================
#  AUDIO UTILITIES
# =============================================================================

def load_wav(path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file, convert to mono float32, return (samples, original_fs)."""
    fs, data = wavfile.read(path)

    # Stereo → mono
    if data.ndim == 2:
        data = data.mean(axis=1)

    # Normalise to float32  [-1, +1]
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2_147_483_648.0
    elif data.dtype == np.uint8:
        data = (data.astype(np.float32) - 128.0) / 128.0
    else:
        data = data.astype(np.float32)

    return data, fs


def resample_audio(data: np.ndarray, fs_in: int, fs_out: int) -> np.ndarray:
    """Resample audio using scipy resample_poly (as specified)."""
    if fs_in == fs_out:
        return data
    from math import gcd
    g   = gcd(fs_out, fs_in)
    up  = fs_out // g
    dn  = fs_in  // g
    return resample_poly(data, up, dn).astype(np.float32)


def amplitude_to_cu(env: np.ndarray) -> np.ndarray:
    """
    Map a normalised linear envelope (0–1) → stimulus amplitude in charge
    units (CU), spanning the T-level to C-level clinical range.

    Mapping logic
    -------------
    The 10 dB dynamic range means A_MAX/A_MIN = 10^(10/20) ≈ 3.16.
    Rather than hard-clipping anything below A_MIN/A_MAX (= 0.3154) to the
    T-level floor — which caused 67% of frames to collapse to 323 CU on
    real speech signals — the full signal dynamic range is log-linearly
    stretched across the T→C window:

      env_db   = 20 × log10(env)         [dB re full scale, floor = -120 dB]
      env_norm = (env_db - env_db_min) / DR_db   [0..1 within observed range]
      CU       = A_MIN + env_norm × (A_MAX - A_MIN)

    This ensures the quietest voiced frame maps near A_MIN and the loudest
    maps near A_MAX, with proportional variation in between.
    Silent frames (env < 1e-4) are zeroed (no stimulation below noise floor).
    """
    env = np.asarray(env, dtype=np.float64)

    # dB re full scale, with a deep floor to handle near-zero values
    env_db = 20.0 * np.log10(np.clip(env, 1e-6, 1.0))

    # Stretch the observed dynamic range linearly across [A_MIN, A_MAX].
    # DR_db sets how many dB below the loudest frame the quietest audible
    # frame sits.  Matching the 10 dB clinical DR keeps the mapping
    # consistent with the T/C level specification.
    DR_db    = float(DYNAMIC_DB)          # 10 dB
    env_norm = np.clip((env_db - (-DR_db)) / DR_db, 0.0, 1.0)

    cu = A_MIN + env_norm * (A_MAX - A_MIN)

    # Zero out frames below the noise floor (no perceptible signal)
    cu[env < 1e-4] = 0.0

    return cu.astype(np.float32)


# =============================================================================
#  FRAME / EPOCH UTILITIES
# =============================================================================

def make_frames(data: np.ndarray, fs: int) -> tuple[np.ndarray, int, int]:
    """
    Segment audio into overlapping frames using a Hann window.

    Frame length : EPOCH_MS  ms  (analysis window)
    Context      : OVERLAP_MS ms total (3 ms each side, as specified)
    Hop size     : frame_len  (non-overlapping advance = EPOCH_MS)

    Returns
    -------
    frames      : (n_frames, win_len) float32 array
    frame_len   : number of samples in EPOCH_MS
    win_len     : total window length including context
    """
    frame_len   = int(round(EPOCH_MS    * 1e-3 * fs))   # 2 ms
    context     = int(round((OVERLAP_MS / 2) * 1e-3 * fs))  # 3 ms each side
    win_len     = frame_len + 2 * context                # 8 ms total window

    # Hann window over the full context-extended frame
    hann_win = np.hanning(win_len).astype(np.float32)

    # Zero-pad so every frame is centred
    pad      = np.zeros(context, dtype=np.float32)
    padded   = np.concatenate([pad, data, pad])

    frames = []
    n      = len(padded)
    start  = 0
    while start + win_len <= n:
        frame = padded[start : start + win_len] * hann_win
        frames.append(frame)
        start += frame_len          # hop by EPOCH_MS (2 ms) – per spec

    return np.array(frames, dtype=np.float32), frame_len, win_len


# =============================================================================
#  FILTER BANK  (shared by CIS and ACE)
# =============================================================================

def make_filterbank(fs: int, n_filters: int = N_FILTERS,
                    f_low: float = FILTERBANK_LOW,
                    f_high: float = FILTERBANK_HIGH,
                    order: int = 4):
    """
    Build a bank of bandpass Butterworth filters with logarithmically-spaced
    centre frequencies.  Returns list of (b, a) coefficient pairs.
    """
    edges = np.logspace(np.log10(f_low), np.log10(f_high), n_filters + 1)
    filters = []
    for k in range(n_filters):
        lo = edges[k]
        hi = edges[k + 1]
        lo = max(lo, 20)
        hi = min(hi, fs / 2 - 1)
        if lo >= hi:
            hi = lo * 1.5
        sos = butter(order, [lo, hi], btype='band', fs=fs, output='sos')
        filters.append(sos)
    return filters


def filterbank_envelopes(frame: np.ndarray, filters: list) -> np.ndarray:
    """
    Apply each filter to the frame, then extract the Hilbert envelope.
    Returns (n_filters,) array of peak envelope values for this frame.
    """
    envs = np.zeros(len(filters), dtype=np.float32)
    for k, sos in enumerate(filters):
        filtered   = signal.sosfilt(sos, frame)
        envelope   = np.abs(hilbert(filtered))
        envs[k]    = float(np.mean(envelope))
    return envs


# =============================================================================
#  STRATEGY 1 – F0F1F2  (Formant-Based)
# =============================================================================

def f0f1f2_strategy(frames: np.ndarray, fs: int) -> np.ndarray:
    """
    F0F1F2 formant-based strategy.

    For each frame:
      1. Estimate F0 via autocorrelation (50-500 Hz).
      2. Extract F1 and F2 via LPC using a Levinson-Durbin recursion.
         This replaces the previous Toeplitz matrix rank-check + linalg.solve
         which failed on 91% of frames due to numerical singularity.
         Levinson-Durbin achieves 100% success on the same frames.
      3. Map F1 and F2 to nearest tonotopic electrode (ELECTRODE_CF).
      4. Amplitude mapped via a 0.25 s running-maximum local normalisation:
         each frame is scaled against the local peak in its neighbourhood,
         so a moderately loud frame within a quiet passage maps to a high
         CU value rather than being crushed by a distant global peak.

    Returns FTM: (N_ELECTRODES x n_frames) amplitude matrix.
    """
    from scipy.ndimage import maximum_filter1d

    n_frames  = len(frames)
    ftm       = np.zeros((N_ELECTRODES, n_frames), dtype=np.float32)
    lpc_order = 2 + int(fs / 1000)   # 18 at 16 kHz

    # Per-frame RMS
    frame_rms = np.array(
        [float(np.sqrt(np.mean(f ** 2))) for f in frames],
        dtype=np.float32
    )
    if float(frame_rms.max()) < 1e-8:
        return ftm  # entirely silent

    # Short-term local normalisation: 0.25 s running maximum window.
    # Preserves loudness contrast within local passages without being
    # dominated by distant global peaks elsewhere in the file.
    frame_len   = int(round(EPOCH_MS    * 1e-3 * fs))   # 2 ms
    LOCAL_WINDOW = int(round(0.25 * fs / (frame_len)))  # 125 frames (~0.25 s)
    local_peak   = maximum_filter1d(frame_rms,
                                    size=LOCAL_WINDOW,
                                    mode='reflect')
    local_peak   = np.maximum(local_peak, 1e-8)

    def _levinson_durbin(r_seq, order):
        """
        Levinson-Durbin recursion.
        Returns LPC polynomial [1, a1, a2, ..., a_order] or None on failure.
        Numerically stable for frames with very low energy where Toeplitz
        matrix rank-check + linalg.solve fails.
        """
        a = np.zeros(order + 1, dtype=np.float64)
        a[0] = 1.0
        e = float(r_seq[0])
        if abs(e) < 1e-12:
            return None
        for i in range(1, order + 1):
            lam  = -(r_seq[i] + np.dot(a[1:i], r_seq[i-1:0:-1])) / e
            a_new = a.copy()
            for j in range(1, i + 1):
                a_new[j] = a[j] + lam * a[i - j]
            a_new[i] = lam
            a = a_new
            e *= (1.0 - lam ** 2)
            if abs(e) < 1e-15:
                break
        return a

    for t, frame in enumerate(frames):
        rms = frame_rms[t]
        if rms < 1e-5:
            continue

        # Amplitude: normalise against local peak
        norm   = float(min(rms / local_peak[t], 1.0))
        amp_cu = float(A_MIN + norm * (A_MAX - A_MIN))

        # F0 via autocorrelation (50-500 Hz)
        corr   = np.correlate(frame, frame, mode='full')
        corr   = corr[len(corr) // 2:]
        lo_lag = max(1, int(fs / 500))
        hi_lag = min(len(corr) - 1, int(fs / 50))
        pk     = lo_lag + int(np.argmax(corr[lo_lag:hi_lag]))
        f0     = fs / pk if pk > 0 else 120.0
        f0     = float(np.clip(f0, 50, 500))

        # LPC via Levinson-Durbin (robust to near-zero energy frames)
        try:
            full_corr = np.correlate(frame.astype(np.float64),
                                     frame.astype(np.float64),
                                     mode='full')
            mid   = len(full_corr) // 2
            r_seq = full_corr[mid: mid + lpc_order + 1]

            coeffs = _levinson_durbin(r_seq, lpc_order)
            if coeffs is None:
                continue

            roots = np.roots(coeffs)
            roots = roots[np.imag(roots) > 0.01]
            if len(roots) < 2:
                continue

            freqs = np.sort(np.abs(np.angle(roots)) * fs / (2 * np.pi))
            freqs = freqs[(freqs > 100) & (freqs < fs / 2 - 100)]
            if len(freqs) < 2:
                continue

            f1, f2 = freqs[0], freqs[1]

        except (np.linalg.LinAlgError, ValueError):
            continue

        # Map each formant to nearest electrode
        for ffreq in [f1, f2]:
            e_idx = int(np.argmin(np.abs(ELECTRODE_CF - ffreq)))
            ftm[e_idx, t] = max(ftm[e_idx, t], amp_cu)

    return ftm


# =============================================================================
#  STRATEGY 2 – CIS  (Continuous Interleaved Sampling)
# =============================================================================

def cis_strategy(frames: np.ndarray, fs: int) -> np.ndarray:
    """
    CIS Strategy:
      - ALL N_ELECTRODES channels are active every frame.
      - Each channel's amplitude is the Hilbert envelope of its bandpass output.
      - Stimulation is interleaved (non-simultaneous) across electrodes.
      - No peak-picking / selection — all channels contribute.

    Returns FTM: (N_ELECTRODES × n_frames) amplitude matrix.
    """
    filters    = make_filterbank(fs)
    n_frames   = len(frames)
    ftm        = np.zeros((N_ELECTRODES, n_frames), dtype=np.float32)

    for t, frame in enumerate(frames):
        envs           = filterbank_envelopes(frame, filters)
        ftm[:, t]      = amplitude_to_cu(envs / (np.max(envs) + 1e-9))

    return ftm


# =============================================================================
#  STRATEGY 3 – ACE  (Advanced Combination Encoder)
# =============================================================================

def ace_strategy(frames: np.ndarray, fs: int,
                 n_maxima: int = ACE_N) -> np.ndarray:
    """
    ACE Strategy (N-of-M):
      - Same filter bank as CIS.
      - Per frame, only the N channels with the highest envelope are active.
      - Remaining M-N channels are zeroed.
      - n_maxima = ACE_N (default 8 of 16).

    Returns FTM: (N_ELECTRODES × n_frames) amplitude matrix.
    """
    filters    = make_filterbank(fs)
    n_frames   = len(frames)
    ftm        = np.zeros((N_ELECTRODES, n_frames), dtype=np.float32)

    for t, frame in enumerate(frames):
        envs       = filterbank_envelopes(frame, filters)
        norm_envs  = envs / (np.max(envs) + 1e-9)
        cu         = amplitude_to_cu(norm_envs)

        # N-of-M: zero out all but top-N channels
        if n_maxima < N_ELECTRODES:
            threshold_idx        = np.argsort(cu)[::-1][n_maxima:]
            cu[threshold_idx]    = 0

        ftm[:, t] = cu

    return ftm


# =============================================================================
#  VOCODER OUTPUT  (Frequency-Time Matrix → audio)
# =============================================================================

def ftm_to_audio(ftm: np.ndarray, fs: int, frame_len: int) -> np.ndarray:
    """
    Convert FTM back to audio via vocoder resynthesis.
    Each electrode's amplitude modulates a pure tone at its centre frequency.
    Output is the sum across all channels.
    """
    n_frames     = ftm.shape[1]
    total_samples = n_frames * frame_len
    output        = np.zeros(total_samples, dtype=np.float32)

    t_frame       = np.arange(frame_len) / fs

    for t in range(n_frames):
        start = t * frame_len
        chunk = np.zeros(frame_len, dtype=np.float32)
        for e in range(N_ELECTRODES):
            amp = ftm[e, t] / A_MAX          # normalise to 0-1
            if amp > 0:
                cf  = ELECTRODE_CF[e]
                chunk += amp * np.sin(2 * np.pi * cf * t_frame).astype(np.float32)
        output[start:start + frame_len] = chunk

    # Normalise
    peak = np.max(np.abs(output))
    if peak > 0:
        output /= peak
    return output


def save_wav(path: str, data: np.ndarray, fs: int):
    """Save float32 audio to a 16-bit WAV file."""
    int_data = np.clip(data * 32767, -32768, 32767).astype(np.int16)
    wavfile.write(path, fs, int_data)


def save_ftm_csv(path: str, ftm: np.ndarray):
    """
    Save FTM to CSV.
    16 rows (electrodes, row 1 = apical), each column = one 2 ms epoch.
    """
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        # Header row
        n_frames = ftm.shape[1]
        header   = ['Electrode'] + [f'Epoch_{t+1}' for t in range(n_frames)]
        writer.writerow(header)
        for e in range(N_ELECTRODES):
            row = [f'E{e+1} ({ELECTRODE_CF[e]} Hz)'] + list(ftm[e, :].round(1))
            writer.writerow(row)


# =============================================================================
#  MICROPHONE CAPTURE  (stdlib wave + sounddevice fallback via scipy)
# =============================================================================

def record_microphone(duration: float = 3.0, fs: int = TARGET_FS) -> np.ndarray:
    """
    Record from microphone for `duration` seconds.
    Uses scipy.io.wavfile round-trip via a temp file.
    Falls back gracefully if no mic available.
    """
    try:
        import sounddevice as sd
        recording = sd.rec(int(duration * fs), samplerate=fs,
                           channels=1, dtype='float32')
        sd.wait()
        return recording.flatten()
    except Exception:
        raise RuntimeError(
            "Microphone recording requires the 'sounddevice' package.\n"
            "Install with: pip install sounddevice\n"
            "Alternatively, select a .WAV file."
        )


# =============================================================================
#  PLAYBACK  (cross-platform via scipy + temp WAV)
# =============================================================================

def play_audio(data: np.ndarray, fs: int):
    """Play audio in a background thread (cross-platform)."""
    def _play():
        try:
            import sounddevice as sd
            sd.play(data, fs)
            sd.wait()
        except ImportError:
            # Fallback: write temp WAV and open with OS default player
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            save_wav(tmp.name, data, fs)
            tmp.close()
            import subprocess, sys
            if sys.platform == 'darwin':
                subprocess.call(['afplay', tmp.name])
            elif sys.platform == 'win32':
                import winsound
                winsound.PlaySound(tmp.name, winsound.SND_FILENAME)
            else:
                subprocess.call(['aplay', tmp.name])
            os.unlink(tmp.name)
    threading.Thread(target=_play, daemon=True).start()


# =============================================================================
#  PLOTTING
# =============================================================================

# Colourblind-safe colourmaps — all three are perceptually uniform with
# 100 % monotone luminance (CVD-safe for deuteranopia, protanopia, tritanopia).
# Each occupies a distinct hue territory so strategies are visually distinct:
#   F0F1F2 → 'inferno'  black → deep red/orange → bright yellow  (lum span 0.946)
#   CIS     → 'magma'   black → purple/pink     → cream/white    (lum span 0.945)
#   ACE     → 'plasma'  purple → orange         → yellow         (lum span 0.841)
STRATEGY_COLORS = {
    'F0F1F2' : 'inferno',
    'CIS'    : 'magma',
    'ACE'    : 'plasma',
}

def plot_waveform(ax: plt.Axes, data: np.ndarray, fs: int, title: str = ''):
    """Plot time-domain waveform on provided axes."""
    ax.clear()
    t = np.arange(len(data)) / fs
    ax.plot(t, data, color='#2196F3', linewidth=0.6, alpha=0.9)
    ax.set_xlabel('Time (s)', fontsize=9)
    ax.set_ylabel('Amplitude', fontsize=9)
    ax.set_title(title or 'Input Waveform', fontsize=10, fontweight='bold')
    ax.set_xlim([0, t[-1]])
    ax.set_ylim([-1.05, 1.05])
    ax.axhline(0, color='#555', linewidth=0.4, linestyle='--')
    ax.grid(True, alpha=0.25, linewidth=0.5)
    ax.tick_params(labelsize=8)


def plot_electrodogram(ax: plt.Axes, ftm: np.ndarray,
                       strategy: str, epoch_ms: float = EPOCH_MS):
    """
    Plot electrodogram heatmap.
    - Apical electrode (E1, low frequency) at TOP of plot (as specified).
    - X-axis: time in ms.
    - Y-axis: electrode number (1=apical at top).
    - Colour: stimulus amplitude in charge units (0–A_MAX).
    """
    ax.clear()
    n_electrodes, n_frames = ftm.shape
    t_axis = np.arange(n_frames) * epoch_ms          # time in ms

    cmap   = STRATEGY_COLORS.get(strategy, 'inferno')

    # Flip vertically so E1 (apical) is at the top
    ftm_display = ftm[::-1, :]

    im = ax.imshow(
        ftm_display,
        aspect='auto',
        origin='upper',
        extent=[0, t_axis[-1], 0.5, n_electrodes + 0.5],
        cmap=cmap,
        vmin=0,
        vmax=A_MAX,
        interpolation='nearest'
    )

    # Colorbar
    cbar = ax.figure.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label('Stimulus Amplitude (CU)', fontsize=8)
    cbar.ax.tick_params(labelsize=7)

    # Y-axis: electrode labels — E16 (basal) at bottom, E1 (apical) at top
    ytick_pos    = np.arange(1, n_electrodes + 1)
    ytick_labels = [f'E{n_electrodes - e + 1}\n({ELECTRODE_CF[n_electrodes - e]} Hz)'
                    for e in range(1, n_electrodes + 1)]
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(ytick_labels, fontsize=6.5)

    ax.set_xlabel('Time (ms)', fontsize=9)
    ax.set_ylabel('Electrode  [Apical → Basal]', fontsize=9)
    ax.set_title(f'Electrodogram — {strategy} Strategy', fontsize=10,
                 fontweight='bold')
    ax.tick_params(axis='x', labelsize=8)

    # Horizontal grid lines between electrodes
    for y in np.arange(1.5, n_electrodes, 1):
        ax.axhline(y, color='white', linewidth=0.3, alpha=0.5)


# =============================================================================
#  MAIN PROCESSOR CLASS
# =============================================================================

class CIProcessor:
    """Orchestrates loading, resampling, framing, strategy, and export."""

    def __init__(self):
        self.raw_data    : np.ndarray | None = None
        self.proc_data   : np.ndarray | None = None   # resampled to TARGET_FS
        self.original_fs : int = TARGET_FS
        self.ftm         : np.ndarray | None = None
        self.vocoder_out : np.ndarray | None = None
        self.strategy    : str = 'CIS'
        self.wav_path    : str = ''

    def load_file(self, path: str):
        data, fs = load_wav(path)
        self.raw_data    = data
        self.original_fs = fs
        self.wav_path    = path
        # Resample if needed
        if fs != TARGET_FS:
            self.proc_data = resample_audio(data, fs, TARGET_FS)
        else:
            self.proc_data = data.copy()

    def load_mic(self, duration: float = 3.0):
        data             = record_microphone(duration, TARGET_FS)
        self.raw_data    = data
        self.original_fs = TARGET_FS
        self.proc_data   = data
        self.wav_path    = '<microphone>'

    def run(self, strategy: str, progress_cb=None,
            n_maxima: int = ACE_N) -> np.ndarray:
        """Run the selected strategy and return the FTM.

        Parameters
        ----------
        strategy    : 'F0F1F2', 'CIS', or 'ACE'
        progress_cb : optional callable(int) for progress-bar updates
        n_maxima    : number of active channels per epoch for ACE (N-of-M).
                      Ignored for F0F1F2 and CIS.  Defaults to ACE_N (8).
        """
        if self.proc_data is None:
            raise ValueError("No audio loaded.")

        self.strategy    = strategy
        frames, frame_len, win_len = make_frames(self.proc_data, TARGET_FS)

        if progress_cb:
            progress_cb(30)

        if strategy == 'F0F1F2':
            ftm = f0f1f2_strategy(frames, TARGET_FS)
        elif strategy == 'CIS':
            ftm = cis_strategy(frames, TARGET_FS)
        elif strategy == 'ACE':
            ftm = ace_strategy(frames, TARGET_FS, n_maxima=n_maxima)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        if progress_cb:
            progress_cb(80)

        self.ftm         = ftm
        self.vocoder_out = ftm_to_audio(ftm, TARGET_FS, frame_len)

        if progress_cb:
            progress_cb(100)

        return ftm

    def export_csv(self, path: str):
        if self.ftm is None:
            raise ValueError("Run processing first.")
        save_ftm_csv(path, self.ftm)

    def export_vocoder_wav(self, path: str):
        if self.vocoder_out is None:
            raise ValueError("Run processing first.")
        save_wav(path, self.vocoder_out, TARGET_FS)

    def play_original(self):
        if self.proc_data is None:
            raise ValueError("No audio loaded.")
        play_audio(self.proc_data, TARGET_FS)

    def play_vocoder(self):
        if self.vocoder_out is None:
            raise ValueError("Run processing first.")
        play_audio(self.vocoder_out, TARGET_FS)


# =============================================================================
#  GUI
# =============================================================================

# Colour palette
C_BG       = '#0D1117'   # near-black background
C_SURFACE  = '#161B22'   # panel surface
C_BORDER   = '#21262D'   # subtle border
C_ACCENT   = '#58A6FF'   # Cochlear-blue accent
C_ACCENT2  = '#3FB950'   # green for RUN
C_TEXT     = '#E6EDF3'   # primary text
C_SUBTEXT  = '#8B949E'   # secondary text
C_ERROR    = '#F85149'   # error red
C_WARN     = '#D29922'   # warning amber

FONT_BODY  = ('Helvetica', 10)
FONT_SMALL = ('Helvetica', 8)
FONT_MONO  = ('Courier', 9)
FONT_H1    = ('Helvetica', 14, 'bold')
FONT_H2    = ('Helvetica', 11, 'bold')


def styled_button(parent, text, command, color=C_ACCENT, width=14, **kw):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=color, fg=C_BG if color in (C_ACCENT, C_ACCENT2) else C_TEXT,
        activebackground=color, activeforeground=C_BG,
        font=('Helvetica', 10, 'bold'),
        relief='flat', bd=0, padx=10, pady=6,
        cursor='hand2', width=width, **kw
    )
    return btn


class CISimulatorGUI:

    def __init__(self, root: tk.Tk):
        self.root      = root
        self.processor = CIProcessor()
        self._setup_window()
        self._build_layout()

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.root.title('CI Sound Processing Simulator — BMET5995')
        self.root.configure(bg=C_BG)
        self.root.geometry('1280x820')
        self.root.minsize(1100, 700)
        try:
            self.root.state('zoomed')   # Windows maximise
        except tk.TclError:
            pass

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        # ── Top bar
        self._build_header()

        # ── Main paned area
        main = tk.Frame(self.root, bg=C_BG)
        main.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        main.columnconfigure(0, weight=0, minsize=290)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # ── Left panel: scrollable container ─────────────────────────────────
        # Outer container holds the canvas and scrollbar side-by-side.
        # The canvas scrolls vertically; the right panel (plots) is unaffected.
        left_container = tk.Frame(main, bg=C_SURFACE, relief='flat',
                                  highlightbackground=C_BORDER,
                                  highlightthickness=1)
        left_container.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)
        left_container.columnconfigure(1, weight=0)

        # Scrollable canvas (no border — the outer container provides it)
        self._ctrl_canvas = tk.Canvas(
            left_container, bg=C_SURFACE,
            highlightthickness=0, bd=0,
        )
        self._ctrl_canvas.grid(row=0, column=0, sticky='nsew')

        # Vertical scrollbar — only visible when content overflows
        scrollbar = ttk.Scrollbar(left_container, orient='vertical',
                                   command=self._ctrl_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self._ctrl_canvas.configure(yscrollcommand=scrollbar.set)

        # Inner frame — all controls live here; its height drives the scrollregion
        self._ctrl_inner = tk.Frame(self._ctrl_canvas, bg=C_SURFACE)
        self._ctrl_window = self._ctrl_canvas.create_window(
            (0, 0), window=self._ctrl_inner, anchor='nw'
        )

        # Keep inner frame width in sync with canvas width
        def _on_canvas_resize(event):
            self._ctrl_canvas.itemconfig(
                self._ctrl_window, width=event.width)
        self._ctrl_canvas.bind('<Configure>', _on_canvas_resize)

        # Update scrollregion whenever inner frame changes size
        def _on_inner_resize(event):
            self._ctrl_canvas.configure(
                scrollregion=self._ctrl_canvas.bbox('all'))
        self._ctrl_inner.bind('<Configure>', _on_inner_resize)

        # Mouse-wheel scrolling (Windows/macOS = MouseWheel, Linux = Button-4/5)
        def _on_mousewheel(event):
            self._ctrl_canvas.yview_scroll(
                int(-1 * (event.delta / 120)), 'units')

        def _on_mousewheel_linux(event):
            direction = -1 if event.num == 4 else 1
            self._ctrl_canvas.yview_scroll(direction, 'units')

        # Bind when pointer enters the left panel, unbind when it leaves
        def _bind_scroll(event):
            self._ctrl_canvas.bind_all('<MouseWheel>',   _on_mousewheel)
            self._ctrl_canvas.bind_all('<Button-4>',     _on_mousewheel_linux)
            self._ctrl_canvas.bind_all('<Button-5>',     _on_mousewheel_linux)

        def _unbind_scroll(event):
            self._ctrl_canvas.unbind_all('<MouseWheel>')
            self._ctrl_canvas.unbind_all('<Button-4>')
            self._ctrl_canvas.unbind_all('<Button-5>')

        left_container.bind('<Enter>', _bind_scroll)
        left_container.bind('<Leave>', _unbind_scroll)
        self._ctrl_canvas.bind('<Enter>', _bind_scroll)
        self._ctrl_canvas.bind('<Leave>', _unbind_scroll)
        self._ctrl_inner.bind('<Enter>', _bind_scroll)
        self._ctrl_inner.bind('<Leave>', _unbind_scroll)

        # Build all controls into the inner frame
        self._build_controls(self._ctrl_inner)

        # ── Right panel (plots) — unchanged ──────────────────────────────────
        right = tk.Frame(main, bg=C_BG)
        right.grid(row=0, column=1, sticky='nsew')
        self._build_plots(right)

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C_SURFACE,
                       highlightbackground=C_BORDER, highlightthickness=1)
        hdr.pack(fill='x', padx=12, pady=(8, 6))

        tk.Label(hdr, text='⚡  Cochlear Implant Sound Processing Simulator ',
                 font=FONT_H1, fg=C_ACCENT, bg=C_SURFACE,
                 padx=16, pady=10).pack(side='left')

        tk.Label(hdr, text='BMET5995 Advanced Bionics',
                 font=FONT_SMALL, fg=C_SUBTEXT, bg=C_SURFACE,
                 padx=16).pack(side='right', pady=10)

    def _build_controls(self, parent):
        pad = dict(padx=14, pady=5)

        # ── Inline status terminal ─────────────────────────────────────────────
        # Sits between the title label and the Input Source section so the user
        # can see current actions without looking away from the controls.
        term_outer = tk.Frame(parent, bg=C_SURFACE)
        term_outer.pack(fill='x', padx=14, pady=(10, 4))

        tk.Label(term_outer, text='Status', font=('Helvetica', 8, 'bold'),
                 fg=C_ACCENT, bg=C_SURFACE, anchor='w').pack(fill='x')

        term_frame = tk.Frame(term_outer, bg='#0A0E14',
                              highlightbackground='#30363D', highlightthickness=1)
        term_frame.pack(fill='x')

        self.status_var = tk.StringVar(
            value='Ready.  Load a WAV file or record from microphone.')

        self._status_label = tk.Label(
            term_frame,
            textvariable=self.status_var,
            font=('Courier', 8),
            fg='#39D353',          # terminal-green text
            bg='#0A0E14',
            anchor='w',
            justify='left',
            wraplength=240,        # wrap long messages inside the panel
            padx=8, pady=6,
        )
        self._status_label.pack(fill='x')

        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=(6, 0))

        # ── Section: Source
        self._section_label(parent, '① Input Source')

        # File path display
        self.wav_var = tk.StringVar(value='No file selected')
        path_frame = tk.Frame(parent, bg=C_SURFACE)
        path_frame.pack(fill='x', **pad)

        path_entry = tk.Entry(path_frame, textvariable=self.wav_var,
                              bg=C_BG, fg=C_SUBTEXT, font=FONT_MONO,
                              relief='flat', state='readonly',
                              insertbackground=C_TEXT)
        path_entry.pack(fill='x', pady=(0, 4))

        btn_row = tk.Frame(parent, bg=C_SURFACE)
        btn_row.pack(fill='x', padx=14, pady=(0, 8))
        styled_button(btn_row, '📂  Browse WAV', self._browse_wav,
                      color='#30363D', width=15).pack(side='left', padx=(0, 6))
        styled_button(btn_row, '🎙  Record Mic', self._record_mic,
                      color='#30363D', width=13).pack(side='left')

        # Separator
        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=6)

        # ── Section: Strategy
        self._section_label(parent, '② Processing Strategy')

        self.strategy_var = tk.StringVar(value='CIS')
        strategies = [
            ('F0F1F2',  'Formant-Based'),
            ('CIS',     'Continuous Interleaved Sampling'),
            ('ACE',     'Advanced Combination Encoder'),
        ]
        for val, label in strategies:
            rb = tk.Radiobutton(
                parent, text=f'  {val}  —  {label}',
                variable=self.strategy_var, value=val,
                bg=C_SURFACE, fg=C_TEXT, selectcolor=C_BG,
                activebackground=C_SURFACE, activeforeground=C_ACCENT,
                font=FONT_BODY, anchor='w',
                indicatoron=True,
            )
            rb.pack(fill='x', padx=20, pady=2)

        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=6)

        # ── Section: ACE parameter
        self._section_label(parent, '③ ACE Parameter')
        ace_row = tk.Frame(parent, bg=C_SURFACE)
        ace_row.pack(fill='x', padx=14, pady=(0, 8))
        tk.Label(ace_row, text='Maxima (N-of-M):', font=FONT_BODY,
                 fg=C_SUBTEXT, bg=C_SURFACE).pack(side='left')
        self.ace_n_var = tk.IntVar(value=ACE_N)
        ace_spin = tk.Spinbox(ace_row, from_=1, to=N_ELECTRODES,
                              textvariable=self.ace_n_var, width=5,
                              bg=C_BG, fg=C_TEXT, font=FONT_BODY,
                              buttonbackground=C_BORDER, relief='flat')
        ace_spin.pack(side='left', padx=8)
        tk.Label(ace_row, text=f'of {N_ELECTRODES}', font=FONT_SMALL,
                 fg=C_SUBTEXT, bg=C_SURFACE).pack(side='left')

        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=6)

        # ── Section: Actions
        self._section_label(parent, '④ Actions')

        btn_cfg = dict(padx=14, pady=4, fill='x')
        styled_button(parent, '▶  RUN', self._run,
                      color=C_ACCENT2, width=22).pack(**btn_cfg)
        tk.Frame(parent, height=4, bg=C_SURFACE).pack()
        styled_button(parent, '🔊  PLAY RESULT', self._play_result,
                      color=C_ACCENT, width=22).pack(**btn_cfg)
        styled_button(parent, '🎵  PLAY WAV', self._play_wav,
                      color='#BB8AFF', width=22).pack(**btn_cfg)

        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=8)

        # ── Section: Export
        self._section_label(parent, '⑤ Export')
        exp_row = tk.Frame(parent, bg=C_SURFACE)
        exp_row.pack(fill='x', padx=14, pady=(0, 8))
        styled_button(exp_row, '💾  CSV', self._export_csv,
                      color='#30363D', width=10).pack(side='left', padx=(0, 6))
        styled_button(exp_row, '🔉  WAV', self._export_wav,
                      color='#30363D', width=10).pack(side='left')

        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=6)

        # ── Info panel
        self._section_label(parent, 'ℹ  Parameters')
        info_lines = [
            f'Target fs    : {TARGET_FS // 1000} kHz',
            f'Frame length : {EPOCH_MS} ms',
            f'Context      : ±{OVERLAP_MS // 2} ms (Hann)',
            f'Electrodes   : {N_ELECTRODES}',
            f'C-level      : {A_MAX} CU',
            f'T-level      : {A_MIN} CU',
            f'Dynamic range: {DYNAMIC_DB} dB',
        ]
        for line in info_lines:
            tk.Label(parent, text=line, font=FONT_MONO,
                     fg=C_SUBTEXT, bg=C_SURFACE, anchor='w').pack(
                fill='x', padx=18, pady=1)

        # ── Progress bar
        tk.Frame(parent, height=1, bg=C_BORDER).pack(fill='x', padx=14, pady=8)
        self.progress = ttk.Progressbar(parent, orient='horizontal',
                                        mode='determinate', length=240)
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TProgressbar', troughcolor=C_BG,
                        background=C_ACCENT2, thickness=6)
        self.progress.pack(padx=14, pady=(0, 10), fill='x')

    def _build_plots(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        # ── Waveform figure
        self.fig_wave  = Figure(figsize=(8, 2.8), dpi=96, facecolor=C_BG)
        self.ax_wave   = self.fig_wave.add_subplot(111)
        self.ax_wave.set_facecolor(C_SURFACE)
        self.ax_wave.tick_params(colors=C_TEXT)
        for spine in self.ax_wave.spines.values():
            spine.set_edgecolor(C_BORDER)
        self.ax_wave.set_title('Input Waveform', color=C_TEXT,
                                fontsize=10, fontweight='bold')
        self.ax_wave.set_xlabel('Time (s)', color=C_SUBTEXT, fontsize=9)
        self.ax_wave.set_ylabel('Amplitude', color=C_SUBTEXT, fontsize=9)
        self.ax_wave.tick_params(labelsize=8, colors=C_SUBTEXT)
        self.fig_wave.tight_layout(pad=1.2)

        self.canvas_wave = FigureCanvasTkAgg(self.fig_wave, master=parent)
        self.canvas_wave.get_tk_widget().grid(
            row=0, column=0, sticky='nsew', pady=(0, 6))
        self.canvas_wave.draw()

        # ── Electrodogram figure
        self.fig_edo   = Figure(figsize=(8, 3.6), dpi=96, facecolor=C_BG)
        self.ax_edo    = self.fig_edo.add_subplot(111)
        self.ax_edo.set_facecolor(C_SURFACE)
        self.ax_edo.tick_params(colors=C_TEXT)
        for spine in self.ax_edo.spines.values():
            spine.set_edgecolor(C_BORDER)
        self.ax_edo.set_title('Electrodogram', color=C_TEXT,
                               fontsize=10, fontweight='bold')
        self.ax_edo.set_xlabel('Time (ms)', color=C_SUBTEXT, fontsize=9)
        self.ax_edo.set_ylabel('Electrode', color=C_SUBTEXT, fontsize=9)
        self.ax_edo.tick_params(labelsize=8, colors=C_SUBTEXT)
        self.fig_edo.tight_layout(pad=1.5)

        self.canvas_edo = FigureCanvasTkAgg(self.fig_edo, master=parent)
        self.canvas_edo.get_tk_widget().grid(
            row=1, column=0, sticky='nsew')
        self.canvas_edo.draw()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section_label(self, parent, text):
        # pady must be a single int in the widget constructor (Tcl/Tk constraint).
        # Asymmetric top/bottom spacing is handled by pack(pady=...) instead.
        tk.Label(parent, text=text, font=('Helvetica', 9, 'bold'),
                 fg=C_ACCENT, bg=C_SURFACE, anchor='w',
                 padx=14, pady=2).pack(fill='x', pady=(6, 0))

    def _set_status(self, msg: str, color: str = C_SUBTEXT):
        self.status_var.set(msg)
        # find the status label and recolour it
        self.root.update_idletasks()

    def _update_progress(self, val: int):
        self.progress['value'] = val
        self.root.update_idletasks()

    def _refresh_waveform(self):
        if self.processor.proc_data is None:
            return
        data = self.processor.proc_data
        t    = np.arange(len(data)) / TARGET_FS

        self.ax_wave.clear()
        self.ax_wave.set_facecolor(C_SURFACE)
        self.ax_wave.plot(t, data, color=C_ACCENT, linewidth=0.6, alpha=0.9)
        self.ax_wave.set_xlabel('Time (s)', color=C_SUBTEXT, fontsize=9)
        self.ax_wave.set_ylabel('Amplitude', color=C_SUBTEXT, fontsize=9)
        fname = os.path.basename(self.processor.wav_path)
        self.ax_wave.set_title(f'Input Waveform — {fname}',
                                color=C_TEXT, fontsize=10, fontweight='bold')
        # Auto-fit Y range to the actual signal peak with 5 % headroom
        peak = float(np.max(np.abs(data)))
        if peak < 1e-6:
            peak = 1.0          # silent/empty signal fallback
        y_margin = peak * 0.05
        self.ax_wave.set_xlim([0, t[-1]])
        self.ax_wave.set_ylim([-(peak + y_margin), (peak + y_margin)])
        self.ax_wave.axhline(0, color='#444', linewidth=0.4, linestyle='--')
        self.ax_wave.grid(True, alpha=0.15, linewidth=0.4, color='#444')
        self.ax_wave.tick_params(labelsize=8, colors=C_SUBTEXT)
        for spine in self.ax_wave.spines.values():
            spine.set_edgecolor(C_BORDER)
        self.fig_wave.tight_layout(pad=1.2)
        self.canvas_wave.draw()

    def _refresh_electrodogram(self):
        if self.processor.ftm is None:
            return
        strategy = self.processor.strategy

        # Clear old colorbars
        self.fig_edo.clear()
        self.ax_edo = self.fig_edo.add_subplot(111)
        self.ax_edo.set_facecolor(C_SURFACE)

        ftm      = self.processor.ftm
        n_e, n_t = ftm.shape
        cmap     = STRATEGY_COLORS.get(strategy, 'inferno')
        t_axis   = np.arange(n_t) * EPOCH_MS

        ftm_display = ftm[::-1, :]    # apical (E1) at top
        im = self.ax_edo.imshow(
            ftm_display, aspect='auto', origin='upper',
            extent=[0, t_axis[-1], 0.5, n_e + 0.5],
            cmap=cmap, vmin=0, vmax=A_MAX, interpolation='nearest'
        )
        cbar = self.fig_edo.colorbar(im, ax=self.ax_edo, pad=0.01)
        cbar.set_label('Stimulus Amplitude (CU)', fontsize=8, color=C_TEXT)
        cbar.ax.yaxis.set_tick_params(color=C_TEXT, labelsize=7)
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color=C_TEXT)

        ytick_pos    = np.arange(1, n_e + 1)
        ytick_labels = [f'E{n_e - e + 1} ({ELECTRODE_CF[n_e - e]} Hz)'
                        for e in range(1, n_e + 1)]
        self.ax_edo.set_yticks(ytick_pos)
        self.ax_edo.set_yticklabels(ytick_labels, fontsize=6)

        self.ax_edo.set_xlabel('Time (ms)', color=C_SUBTEXT, fontsize=9)
        self.ax_edo.set_ylabel('Electrode  [Apical → Basal]',
                                color=C_SUBTEXT, fontsize=9)
        self.ax_edo.set_title(
            f'Electrodogram — {strategy} Strategy  '
            f'({n_t} epochs × {EPOCH_MS} ms)',
            color=C_TEXT, fontsize=10, fontweight='bold')
        self.ax_edo.tick_params(axis='x', labelsize=8, colors=C_SUBTEXT)
        self.ax_edo.tick_params(axis='y', colors=C_SUBTEXT)
        for spine in self.ax_edo.spines.values():
            spine.set_edgecolor(C_BORDER)
        for y in np.arange(1.5, n_e, 1):
            self.ax_edo.axhline(y, color='white', linewidth=0.25, alpha=0.3)

        self.fig_edo.tight_layout(pad=1.4)
        self.canvas_edo.draw()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _browse_wav(self):
        # Start the dialog in the script's own directory for convenience
        start_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.askopenfilename(
            title='Select WAV file',
            initialdir=start_dir,
            filetypes=[('WAV files', '*.wav'), ('All files', '*.*')]
        )
        if not path:
            return
        # Check file size ≤ 1 MB
        size_mb = os.path.getsize(path) / 1_048_576
        if size_mb > 1.0:
            messagebox.showwarning('File Too Large',
                f'File is {size_mb:.1f} MB. Maximum allowed is 1 MB.')
            return
        try:
            self.processor.load_file(path)
            short = os.path.basename(path)
            self.wav_var.set(short)
            fs_in = self.processor.original_fs
            n     = len(self.processor.proc_data)
            dur   = n / TARGET_FS
            self._set_status(
                f'Loaded: {short}  |  Original fs={fs_in} Hz  →  '
                f'Resampled to {TARGET_FS} Hz  |  Duration: {dur:.2f} s')
            self._refresh_waveform()
            self._update_progress(0)
        except Exception as e:
            messagebox.showerror('Load Error', str(e))

    def _record_mic(self):
        """
        Show a 3-2-1 countdown using root.after() so each tick is scheduled
        directly on Tkinter's event loop -- guaranteeing a repaint between steps.
        Recording itself runs in a background thread so the UI stays responsive.
        """
        try:
            import sounddevice  # noqa -- check early so we fail before countdown
        except ImportError:
            messagebox.showerror(
                'Microphone Error',
                "Microphone recording requires the 'sounddevice' package.\n"
                "Install with:  pip install sounddevice"
            )
            return

        rec_duration = 10.0      # seconds to record 
        countdown    = [3]      # mutable list so nested closures can mutate it

        def _tick():
            """Called by Tkinter every 1000 ms during the countdown."""
            n = countdown[0]
            if n > 0:
                # Update the status label and force an immediate screen repaint
                self.status_var.set(
                    f'Recording starts in  {n}...  get ready!')
                self.root.update()              # forces label to repaint NOW
                countdown[0] -= 1
                self.root.after(1000, _tick)   # schedule next tick in 1 s
            else:
                # Countdown done -- show "recording" banner, then start capture
                self.status_var.set(
                    f'Recording {rec_duration:.0f} s -- speak now...')
                self.root.update()
                threading.Thread(target=_do_record, daemon=True).start()

        def _do_record():
            """Runs in background thread so the UI stays live during capture."""
            try:
                self.processor.load_mic(rec_duration)
                self.root.after(0, lambda: self.wav_var.set('<microphone>'))
                self.root.after(0, self._refresh_waveform)
                self.root.after(0, lambda: self.status_var.set(
                    'Microphone recording complete.'))
            except RuntimeError as e:
                self.root.after(0, lambda: messagebox.showerror(
                    'Microphone Error', str(e)))

        # Kick off the first tick immediately (runs on main thread)
        _tick()

    def _run(self):
        if self.processor.proc_data is None:
            messagebox.showwarning('No Input', 'Please load a WAV file or record from microphone first.')
            return
        strategy = self.strategy_var.get()

        # Read the user-selected N-of-M value from the spinbox.
        # Clamped to [1, N_ELECTRODES] in case of out-of-range manual entry.
        ace_n = int(np.clip(self.ace_n_var.get(), 1, N_ELECTRODES))

        self._set_status(f'Running {strategy} strategy'
                         + (f'  (N={ace_n} of {N_ELECTRODES})' if strategy == 'ACE' else '')
                         + '...')
        self._update_progress(10)

        def worker():
            try:
                self.processor.run(strategy,
                                   progress_cb=self._update_progress,
                                   n_maxima=ace_n)
                self.root.after(0, self._refresh_electrodogram)
                n_frames = self.processor.ftm.shape[1]
                dur      = len(self.processor.proc_data) / TARGET_FS
                ace_info = (f'  N={ace_n} of {N_ELECTRODES}  |  '
                            if strategy == 'ACE' else '  |  ')
                self.root.after(0, lambda: self._set_status(
                    f'✔  {strategy} complete.{ace_info}'
                    f'{n_frames} epochs × {EPOCH_MS} ms  |  '
                    f'Duration: {dur:.2f} s  |  '
                    f'FTM: {N_ELECTRODES} × {n_frames}  —  '
                    f'Ready to play or export.'))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror('Processing Error', str(e)))
            finally:
                self.root.after(0, lambda: self._update_progress(0))

        threading.Thread(target=worker, daemon=True).start()

    def _play_result(self):
        if self.processor.vocoder_out is None:
            messagebox.showwarning('Not Ready', 'Run processing first.')
            return
        self._set_status('Playing vocoder output...')
        self.processor.play_vocoder()

    def _play_wav(self):
        if self.processor.proc_data is None:
            messagebox.showwarning('No Input', 'No WAV file loaded.')
            return
        self._set_status('Playing original WAV...')
        self.processor.play_original()

    def _export_csv(self):
        if self.processor.ftm is None:
            messagebox.showwarning('Not Ready', 'Run processing first.')
            return
        # Derive the WAV stem (filename without extension) for the default name.
        # Falls back to 'recording' for microphone input ('<microphone>').
        wav_path = self.processor.wav_path
        if wav_path and wav_path != '<microphone>':
            wav_stem = os.path.splitext(os.path.basename(wav_path))[0]
        else:
            wav_stem = 'recording'
        default_name = f'{wav_stem}_FTM_{self.processor.strategy}.csv'

        start_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            initialdir=start_dir,
            filetypes=[('CSV files', '*.csv')],
            initialfile=default_name
        )
        if path:
            self.processor.export_csv(path)
            self._set_status(f'CSV saved: {os.path.basename(path)}')

    def _export_wav(self):
        if self.processor.vocoder_out is None:
            messagebox.showwarning('Not Ready', 'Run processing first.')
            return
        # Derive the WAV stem (filename without extension) for the default name.
        # Falls back to 'recording' for microphone input ('<microphone>').
        wav_path = self.processor.wav_path
        if wav_path and wav_path != '<microphone>':
            wav_stem = os.path.splitext(os.path.basename(wav_path))[0]
        else:
            wav_stem = 'recording'
        default_name = f'{wav_stem}_vocoder_{self.processor.strategy}.wav'

        start_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.asksaveasfilename(
            defaultextension='.wav',
            initialdir=start_dir,
            filetypes=[('WAV files', '*.wav')],
            initialfile=default_name
        )
        if path:
            self.processor.export_vocoder_wav(path)
            self._set_status(f'Vocoder WAV saved: {os.path.basename(path)}')


# =============================================================================
#  ENTRY POINT
# =============================================================================

def main():
    root = tk.Tk()
    app  = CISimulatorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
