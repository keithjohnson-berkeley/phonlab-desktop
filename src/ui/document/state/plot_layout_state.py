from dataclasses import dataclass


@dataclass
class PlotLayoutState:
    is_waveform: bool = True
    is_spectrogram: bool = False
    is_text_notes: bool = False
