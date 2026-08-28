import threading
import time

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from core.play_audio.entity.latency_info import LatencyInfo


class AudioThread(QRunnable):

    TARGET_CHUNK_MS = 20

    def __init__(self, audio_data: np.ndarray, fs: int):
        super().__init__()

        self.signals = AudioThreadSignals()

        self._should_stop = False

        # Set once this thread's OutputStream has been fully closed, so
        # callers can wait for PortAudio to be quiescent before another
        # AudioThread touches the global PortAudio session (sd._terminate/
        # _initialize below). Without this, a new thread can re-init
        # PortAudio while a previous thread's stream is still shutting
        # down, which crashes with PortAudioError -9986 (paInternalError).
        self.done_event = threading.Event()

        self._audio_data = audio_data
        self._fs = fs

    def run(self):
        try:
            # Force PortAudio to re-scan its device list
            sd._terminate()
            sd._initialize()

            audio_data = np.ascontiguousarray(self._audio_data, dtype="float32")
            channels = audio_data.shape[1] if audio_data.ndim > 1 else 1

            chunk_size = int(self._fs * self.TARGET_CHUNK_MS / 1000)

            # Fresh OutputStream with currently selected system default
            with self._open_stream(self._fs, channels) as stream:
                self._audible_start_time = time.monotonic() + stream.latency
                self.signals.latency.emit(LatencyInfo(stream.latency, time.monotonic() + stream.latency))

                offset = 0
                while offset < len(audio_data) and not self._should_stop:
                    chunk = audio_data[offset : offset + chunk_size]
                    stream.write(chunk)
                    offset += chunk_size

                if not self._should_stop:
                    # Wait for audio backend buffer to drain
                    time.sleep(stream.latency)

            self.signals.finished.emit()

        except Exception as e:
            self.signals.error.emit(str(e))
            raise
        finally:
            self.done_event.set()
    
    def _open_stream(self, samplerate: int, channels: int) -> sd.OutputStream:
        """Open an OutputStream, falling back to a more conservative latency
        if the driver rejects the previous choice (some Windows audio
        drivers can't honor a low-latency request)."""
        last_err: Exception | None = None
        for latency in (0.1, "low", "high", None):
            try:
                return sd.OutputStream(
                    samplerate=samplerate,
                    channels=channels,
                    dtype="float32",
                    latency=latency,
                )
            except sd.PortAudioError as e:
                last_err = e
        raise last_err

    def stop(self):
        self._should_stop = True
       

class AudioThreadSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    latency = pyqtSignal(object)
