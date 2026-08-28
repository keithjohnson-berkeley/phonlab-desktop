from dataclasses import dataclass


@dataclass
class PlaybackState:
    is_playing: bool = False
    position: float = 0.0
    high_latency: bool = False
