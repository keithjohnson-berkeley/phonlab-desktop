from dataclasses import replace

import numpy as np
from PyQt6.QtCore import QTimer, pyqtSlot

import phonlab as phon
from core.load_audio.entity.audio_document import AudioDocument
from core.load_audio.entity.audio_open_options import AudioOpenOptions
from core.load_audio.entity.audio_signal import AudioSignal
from core.load_audio.load_audio import LoadAudio
from core.play_audio.audio_player import AudioPlayer
from core.play_audio.entity.playback_poll import PlaybackPoll
from core.spectrogram.compute_sgram import ComputeSpectrogram
from core.spectrogram.compute_sgram_mmap import ComputeSpectrogramMmap
from core.spectrogram.entity.spectrogram import Spectrogram
from core.spectrogram.entity.spectrogram_mmap import SpectrogramMmap
from res.constants import MAX_SGRAM_LENGTH
from ui.base.view_model import ViewModel
from ui.document.state.audio_wave_state import AudioWaveState, to_audio_wave_state
from ui.document.state.document_window_state import DocumentWindowState
from ui.document.state.load_progress_state import LoadProgressState
from ui.document.state.playback_state import PlaybackState
from ui.document.state.plot_layout_state import PlotLayoutState
from ui.document.state.select_state import SelectState
from ui.document.state.sgram_state import SpectrogramState
from ui.document.state.status_message_state import StatusMessageState

LATENCY_WARNING_THRESHOLD_S = 0.1  # audacity's own reference for "robust" latency


class DocumentViewModel(ViewModel):
    def __init__(self):
        super().__init__()
        self.audio_wave_state: AudioWaveState = AudioWaveState()
        self.raw_wave_state: AudioWaveState = AudioWaveState()
        self.audio_document: AudioDocument | None = None
        self.sgram_state: SpectrogramState = SpectrogramState()
        self.is_audio_playing = False
        self.select_state: SelectState = SelectState()
        self.document_window_state: DocumentWindowState = DocumentWindowState()
        self.plot_layout_state: PlotLayoutState = PlotLayoutState()
        self.playback_state = PlaybackState()

        self.click_timer: QTimer | None = None

        self.audio_player = AudioPlayer()

    def load_audio(self, filepath: str, options: AudioOpenOptions):
        # LoadAudio yields twice: a fast preview of the first window, then
        # the fully loaded file once it's ready (which can take a while for
        # a long recording). is_preview tracks which one this callback is
        # currently handling.
        is_preview = [True]
        @pyqtSlot(object)
        def on_success(audio_document: AudioDocument):
            preview = is_preview[0]
            is_preview[0] = False

            self.audio_document = audio_document
            audio_signal = audio_document.channels[audio_document.primary_channel]

            if audio_document.original_channels is not None:
                raw_signal = AudioSignal(
                    audio_document.original_channels[audio_document.primary_channel],
                    audio_document.original_fs,
                )
            else:
                # Preview yield: the unprocessed file hasn't been read yet,
                # so fall back to the prepped preview signal for display.
                raw_signal = audio_signal

            if preview:
                self.remove_selection()

            self.audio_wave_state = to_audio_wave_state(audio_signal)
            self.raw_wave_state = to_audio_wave_state(raw_signal)
            self.state_changed.emit(self.audio_wave_state)

            signal_end = len(audio_signal.x) - 1
            window_end = min(signal_end, MAX_SGRAM_LENGTH * audio_signal.fs)
            if preview:
                # Nothing has loaded past the preview yet, so scrolling is
                # capped to what's currently in memory.
                self.document_window_state = replace(
                    self.document_window_state,
                    start=0,
                    end=window_end,
                    max_start=(signal_end - window_end),
                )
            else:
                # Keep whatever the user is currently looking at; just
                # widen how far they're now allowed to scroll.
                self.document_window_state = replace(
                    self.document_window_state,
                    max_start=(signal_end - window_end),
                )
            self.state_changed.emit(self.document_window_state)

            self.state_changed.emit(LoadProgressState(is_loading=preview))

            if not preview:
                shown = (
                    self.document_window_state.end - self.document_window_state.start
                )
                msg = self.tr(
                    "Duration shown {:.3f} seconds, out of {:.3f} seconds"
                ).format(shown / audio_signal.fs, len(audio_signal.x) / audio_signal.fs)
                self.state_changed.emit(StatusMessageState(msg))

        use_case = LoadAudio(
            filepath,
            target_fs=options.target_fs,
            channel_mode=options.channel_mode,
            retained_channels=options.retained_channels,
            primary_channel=options.primary_channel,
        )
        self.launch_use_case("load_audio", use_case, on_success, self.on_error)


    def show_spectrogram(self, show: bool):
        self.plot_layout_state = replace(self.plot_layout_state, is_spectrogram=show)
        self.state_changed.emit(self.plot_layout_state)

    def compute_spectrogram(self):
        x, fs = self.audio_wave_state.x, self.audio_wave_state.fs
        start, end = self.document_window_state.start, self.document_window_state.end

        if (end - start) / fs > MAX_SGRAM_LENGTH:
            self.sgram_state = replace(self.sgram_state, is_showing=False)
            self.state_changed.emit(self.sgram_state)
            return

        self.load_spectrogram_window(x, fs, start, end)
        self.load_spectrogram_mmap(x, fs)

    def load_spectrogram_window(self, x: np.ndarray, fs: int, start: int, end: int):
        if (
            self.sgram_state.sxx_mmap is not None
            and self.sgram_state.t_mmap is not None
            and self.sgram_state.samples_computed > end
        ):
            frames_computed = self.sgram_state.frames_computed
            sfr = np.abs(
                self.sgram_state.t_mmap[:frames_computed]
                - self.audio_wave_state.t[start]
            ).argmin()
            efr = np.abs(
                self.sgram_state.t_mmap[:frames_computed] - self.audio_wave_state.t[end]
            ).argmin()

            t_window = np.array(self.sgram_state.t_mmap[sfr:efr])
            sxx_window = np.array(self.sgram_state.sxx_mmap[:, sfr:efr])

            self.sgram_state = replace(
                self.sgram_state,
                t_window=t_window,
                sxx_window=sxx_window,
                is_showing=True,
            )
            self.state_changed.emit(self.sgram_state)
        else:
            t, f, sxx = phon.compute_sgram(x[start:end], fs, 0.008, 0.003, 9)

            self.sgram_state = replace(
                self.sgram_state,
                t_window=t + (start / fs),
                sxx_window=sxx,
                f=f,
                is_showing=True,
            )
            self.state_changed.emit(self.sgram_state)

            @pyqtSlot(object)
            def on_success(sgram: Spectrogram):
                self.sgram_state = replace(
                    self.sgram_state,
                    t_window=sgram.t + (start / fs),
                    sxx_window=sgram.sxx,
                    f=sgram.f,
                    is_showing=True,
                )
                self.state_changed.emit(self.sgram_state)

            use_case = ComputeSpectrogram(x[start:end], fs)
            self.launch_use_case("sgram_window", use_case, on_success, self.on_error)

    def load_spectrogram_mmap(self, x, fs):
        if self.sgram_state.sxx_mmap is None or self.sgram_state.t_mmap is None:

            @pyqtSlot(object)
            def on_success(sgram: SpectrogramMmap):
                self.sgram_state = replace(
                    self.sgram_state,
                    sxx_mmap=sgram.sxx_mmap,
                    t_mmap=sgram.t_mmap,
                    frames_per_sec=sgram.frames_per_sec,
                    frames_computed=sgram.frames_computed,
                    samples_computed=sgram.samples_computed,
                )

            use_case = ComputeSpectrogramMmap(x, fs)
            self.launch_use_case(
                "sgram_mmap", use_case, on_success, self.on_error, only_once=True
            )

    def play_audio(self, x: np.ndarray, fs: int, start: int):
        self.stop_audio()

        @pyqtSlot(object)
        def on_poll(playback_poll: PlaybackPoll):
            high_latency = playback_poll.latency > LATENCY_WARNING_THRESHOLD_S

            if high_latency and not self.playback_state.high_latency:
                msg = self.tr(
                    "System audio latency is a little long ({:.0f} ms). Consider using a different audio device."
                ).format(playback_poll.latency  * 1000)
                self.state_changed.emit(StatusMessageState(msg))

            self.playback_state = PlaybackState(playback_poll.is_playing, playback_poll.current_time, high_latency)
            self.state_changed.emit(self.playback_state)

        self.audio_player.playback_poll.connect(on_poll)
        self.audio_player.play(x, fs, start / self.audio_wave_state.fs)

    def stop_audio(self):
        self.audio_player.stop()

    def close_threads(self):
        self.audio_player.stop()
        super().close_threads()

    def go_back(self):
        window_size = self.document_window_state.end - self.document_window_state.start
        self.move_start(self.document_window_state.start - window_size)

    def advance(self):
        window_size = self.document_window_state.end - self.document_window_state.start
        self.move_start(self.document_window_state.start + window_size)

    def move_start_by_fraction(self, fraction: float):
        start = self.document_window_state.start
        end = self.document_window_state.end
        scroll_amount = int((end - start) * fraction)

        self.move_start(start + scroll_amount)

    def move_start(self, new_start: int):
        start = self.document_window_state.start
        end = self.document_window_state.end
        window_size = end - start
        max_end = len(self.audio_wave_state.x) - 1

        if new_start < start:
            new_start = max(0, new_start)
            new_end = new_start + window_size
        else:
            new_end = min(max_end, new_start + window_size)
            new_start = new_end - window_size

        self.document_window_state = replace(
            self.document_window_state, start=new_start, end=new_end
        )
        self.state_changed.emit(self.document_window_state)

    def start_selection(self, x_pos: float):
        self.select_state = replace(
            self.select_state,
            is_selected=True,
            sel_start=x_pos,
            sel_end=x_pos,
            sel_anchor=x_pos,
        )
        self.state_changed.emit(self.select_state)

    def continue_selection(self, x_pos: float):
        sel_start = self.select_state.sel_start
        sel_end = self.select_state.sel_end

        if x_pos >= self.select_state.sel_anchor:
            sel_start = self.select_state.sel_anchor
            sel_end = min(x_pos, self.audio_wave_state.t[-1])
        elif x_pos < self.select_state.sel_anchor:
            sel_start = max(x_pos, 0.0)
            sel_end = self.select_state.sel_anchor

        self.select_state = replace(
            self.select_state, sel_start=sel_start, sel_end=sel_end
        )
        self.state_changed.emit(self.select_state)

        msg = self.tr("Select: {:.3f} to {:.3f} ({:.3f}s)").format(
            sel_start, sel_end, sel_end - sel_start
        )
        self.state_changed.emit(StatusMessageState(msg))

    def remove_selection(self):
        self.select_state = SelectState()
        self.state_changed.emit(self.select_state)

    def zoom_if_in_selection(self, x_pos: float):
        x, fs = self.audio_wave_state.x, self.audio_wave_state.fs
        max_end = len(x) - 1
        sel_start, sel_end = self.select_state.sel_start, self.select_state.sel_end
        if sel_end > x_pos > sel_start:
            start = int(sel_start * fs)
            end = int(sel_end * fs)
            window_length = end - start
            self.document_window_state = replace(
                self.document_window_state, start=start, end=end, max_start=max_end - window_length
            )
            self.state_changed.emit(self.document_window_state)

            self.remove_selection()

    def center_on_selection(self):
        if not self.select_state.is_selected:
            msg = self.tr("No selection to center on")
            self.state_changed.emit(StatusMessageState(msg))
            return

        # Calculate the center of the selection in samples
        sel_start_samples = int(self.select_state.sel_start * self.audio_wave_state.fs)
        sel_end_samples = int(self.select_state.sel_end * self.audio_wave_state.fs)
        sel_center_samples = (sel_start_samples + sel_end_samples) // 2

        # Calculate new window bounds centered on selection
        window_size = self.document_window_state.end - self.document_window_state.start
        new_start = sel_center_samples - (window_size // 2)

        self.move_start(new_start)

    def zoom_out(self, factor: float = 2):
        start, end = self.document_window_state.start, self.document_window_state.end

        center = start + int((end - start) / 2)
        new_size = int((end - start) * factor)
        max_end = len(self.audio_wave_state.x) - 1

        new_end = center + int(new_size / 2)
        new_end = min(new_end, max_end)
        new_start = max(0, new_end - new_size)
        window_length = new_end - new_start

        self.document_window_state = replace(
            self.document_window_state, start=new_start, end=new_end, max_start=(max_end - window_length)
        )
        self.state_changed.emit(self.document_window_state)

    def zoom_in(self, factor: float = 2):
        start, end = self.document_window_state.start, self.document_window_state.end

        center = start + int((end - start) / 2)
        new_size = int((end - start) / factor)
        new_size = max(new_size, 50)

        new_end = center + int(new_size / 2)
        new_start = new_end - new_size

        max_end = len(self.audio_wave_state.x) - 1
        window_length = new_end - new_start

        self.document_window_state = replace(
            self.document_window_state, start=new_start, end=new_end, max_start=(max_end - window_length)
        )
        self.state_changed.emit(self.document_window_state)

    def show_all(self):
        end = len(self.audio_wave_state.x) - 1
        self.document_window_state = DocumentWindowState(start=0, end=end)
        self.state_changed.emit(self.document_window_state)

    def play_selected_audio(self):
        start = int(self.select_state.sel_start * self.audio_wave_state.fs)
        end = int(self.select_state.sel_end * self.audio_wave_state.fs)

        if start != end:
            section = self.audio_wave_state.x[start:end]
            self.play_audio(section, self.audio_wave_state.fs, start=start)

    def play_visible_audio(self):
        start, end = self.document_window_state.start, self.document_window_state.end

        if len(self.audio_wave_state.x) > 0:
            section = self.audio_wave_state.x[start:end]
            self.play_audio(section, self.audio_wave_state.fs, start=start)

    @pyqtSlot(object)
    def on_error(self, err):
        print(err)
