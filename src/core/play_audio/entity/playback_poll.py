from dataclasses import dataclass


@dataclass
class PlaybackPoll:
    current_time: float
    latency: float
    is_playing: bool
