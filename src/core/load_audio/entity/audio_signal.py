from dataclasses import dataclass

import numpy as np


@dataclass
class AudioSignal:
    x: np.ndarray
    fs: int
