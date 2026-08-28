from dataclasses import dataclass

import numpy as np

from core.load_audio.entity.audio_signal import AudioSignal


@dataclass
class AudioDocument:
    channels: dict[int, AudioSignal]
    primary_channel: int
    channel_mode: str
    original_channels: list[np.ndarray] | None = None
    original_fs: int | None = None
