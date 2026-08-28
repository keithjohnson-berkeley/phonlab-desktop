from dataclasses import dataclass


@dataclass
class LatencyInfo:
    latency: float
    audible_start_time: float
