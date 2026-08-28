from dataclasses import dataclass, field

import numpy as np

from core.load_audio.entity.audio_signal import AudioSignal


@dataclass
class AudioWaveState:
    x: np.ndarray = field(default_factory=lambda: np.zeros(0))
    fs: int = 0
    min_x: float = 0.0
    max_x: float = 0.0
    x_range: float = 0.0
    t: np.ndarray = field(default_factory=lambda: np.zeros(0))


def to_audio_wave_state(audio_signal: AudioSignal) -> AudioWaveState:
    x, fs = audio_signal.x, audio_signal.fs
    # Cast to plain Python floats regardless of x's dtype (e.g. raw audio
    # loads as float32 while processed audio comes out float64) — pyqtgraph
    # mixes these into float64 view-range math and raises spurious
    # "overflow encountered in cast" warnings when fed a float32 scalar.
    min_x = float(np.min(x))
    max_x = float(np.max(x))
    x_range = max_x - min_x
    t = np.arange(len(x)) / fs

    return AudioWaveState(x, fs, min_x, max_x, x_range, t)
