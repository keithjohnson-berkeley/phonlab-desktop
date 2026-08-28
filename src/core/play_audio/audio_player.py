import time

import numpy as np
from PyQt6.QtCore import QObject, QThreadPool, QTimer, pyqtSignal, pyqtSlot

from core.play_audio.audio_thread import AudioThread
from core.play_audio.entity.latency_info import LatencyInfo
from core.play_audio.entity.playback_poll import PlaybackPoll


class AudioPlayer(QObject):
    playback_poll = pyqtSignal(object)
    playback_error = pyqtSignal(str)

    thread_pool: QThreadPool = QThreadPool.globalInstance()

    PLAYBACK_POLL_MS = 33
    STOP_TIMEOUT_S = 2.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_thread: AudioThread | None = None

        self._start_time = 0.0
        self._audible_start_time = float("inf")
        self._audio_length_time = 0.0
        self._latency = 0.0

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(self.PLAYBACK_POLL_MS)
        self.poll_timer.timeout.connect(self._poll_playback)

    def _get_current_time(self) -> float:
        current_time = max(0.0, time.monotonic() - self._audible_start_time)
        current_time = min(current_time, self._audio_length_time)
        return current_time + self._start_time

    def _is_playing(self) -> bool:
        return self._current_thread is not None

    def play(self, audio_data: np.ndarray, fs: int, start_time: float):
        """Play audio using whatever the current default output device is."""
        # Block until any previous AudioThread has fully closed its
        # OutputStream before starting a new one. AudioThread re-inits the
        # global PortAudio session on startup, which crashes with
        # PortAudioError -9986 if it races with another thread's stream
        # still being torn down.
        self.stop()

        self._start_time = start_time
        self._audible_start_time = float("inf")
        self._audio_length_time = len(audio_data) / fs

        audio_thread = AudioThread(audio_data, fs)

        # audio_thread's signals cross from the worker thread via a queued
        # connection, so a signal from a thread we already stopped can be
        # delivered after we've moved on to a new one. Bind the thread it
        # came from so the handler can ignore stale, superseded callbacks.
        audio_thread.signals.finished.connect(lambda: self._on_thread_finished(audio_thread))
        audio_thread.signals.error.connect(lambda msg: self._on_error(msg, audio_thread))
        audio_thread.signals.latency.connect(self._on_latency)

        self._current_thread = audio_thread

        self.thread_pool.start(audio_thread)
        self.poll_timer.start()

    @pyqtSlot()
    def _poll_playback(self):
        self.playback_poll.emit(PlaybackPoll(self._get_current_time(), self._latency, True))

    def _on_thread_finished(self, thread: "AudioThread"):
        if thread is not self._current_thread:
            return
        self.playback_poll.emit(PlaybackPoll(self._get_current_time(), self._latency, False))
        self.poll_timer.stop()
        self._current_thread = None

    @pyqtSlot(object)
    def _on_latency(self, latency_info: LatencyInfo):
        self._latency = latency_info.latency
        self._audible_start_time = latency_info.audible_start_time

    def _on_error(self, message: str, thread: "AudioThread"):
        if thread is not self._current_thread:
            return
        self.playback_error.emit(message)
        self.poll_timer.stop()
        self._current_thread = None

    def stop(self):
        thread = self._current_thread
        if thread is None:
            return

        thread.stop()
        thread.done_event.wait(self.STOP_TIMEOUT_S)
        self._current_thread = None

        # By now the thread has fully torn down, so report the stopped
        # state ourselves rather than waiting on its (possibly delayed)
        # queued `finished` signal.
        self.playback_poll.emit(PlaybackPoll(self._get_current_time(), self._latency, False))
        self.poll_timer.stop()
