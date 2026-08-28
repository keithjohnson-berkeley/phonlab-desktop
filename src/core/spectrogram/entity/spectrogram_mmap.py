from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SpectrogramMmap:
    t_mmap: np.memmap
    sxx_mmap: np.memmap
    frames_per_sec: float
    frames_computed: int
    samples_computed: int
