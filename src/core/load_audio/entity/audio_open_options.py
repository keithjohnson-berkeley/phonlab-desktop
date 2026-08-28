from dataclasses import dataclass


@dataclass
class AudioOpenOptions:
    target_fs: int
    channel_mode: str  # "mono" | "stereo" | "multichannel"
    retained_channels: list[int]
    primary_channel: int
