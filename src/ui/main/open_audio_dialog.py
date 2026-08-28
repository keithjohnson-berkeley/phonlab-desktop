from pathlib import Path

import soundfile as sf
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

import phonlab as phon
from core.load_audio.entity.audio_open_options import AudioOpenOptions
from res.constants import MAX_SGRAM_LENGTH

CHANNEL_MODE_MONO = "mono"
CHANNEL_MODE_STEREO = "stereo"
CHANNEL_MODE_MULTICHANNEL = "multichannel"

DEFAULT_SAMPLE_RATE = 16000


def _channel_label(index: int, native_channels: int) -> str:
    if index == 0 and native_channels >= 2:
        return "Channel 1 (Left)"
    if index == 1 and native_channels >= 2:
        return "Channel 2 (Right)"
    return f"Channel {index + 1}"


def _mono_options() -> AudioOpenOptions:
    return AudioOpenOptions(
        target_fs=DEFAULT_SAMPLE_RATE,
        channel_mode=CHANNEL_MODE_MONO,
        retained_channels=[0],
        primary_channel=0,
    )


class OpenAudioDialog(QDialog):
    """Lets the user pick channel mode and primary channel for a file about
    to be opened, after reporting its native format. Skipped for
    single-channel files, and for stereo files whose two channels turn out
    to be duplicates of each other (those are opened as mono automatically,
    using the left channel)."""

    @staticmethod
    def get_options(filename: str, parent=None) -> AudioOpenOptions | None:
        dlg = OpenAudioDialog(filename, parent)
        if not dlg.is_valid:
            return None

        if dlg.native_channels <= 1:
            return _mono_options()

        if dlg.native_channels == 2:
            chan_a, chan_b, _fs = phon.loadsig(
                filename, chansel=[0, 1], duration=MAX_SGRAM_LENGTH
            )
            if phon.channels_are_duplicates(chan_a, chan_b):
                QMessageBox.warning(
                    parent,
                    dlg.tr("Duplicate channels"),
                    dlg.tr(
                        "the channels of this audio file appear to be "
                        "duplicates of the same audio - we will treat it as "
                        "a mono audio file."
                    ),
                )
                return _mono_options()

        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.build_options()
        return None

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.is_valid = True

        try:
            info = sf.info(filename)
            self.native_channels = info.channels
            self.native_fs = int(info.samplerate)
        except Exception as e:
            self.is_valid = False
            QMessageBox.critical(
                parent, self.tr("Cannot open file"), self.tr(f"{filename}\n\n{e}")
            )
            return

        self.setWindowTitle(self.tr("Open Audio File"))

        layout = QVBoxLayout(self)

        info_layout = QFormLayout()
        info_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        info_layout.addRow(self.tr("File:"), QLabel(Path(filename).name))
        info_layout.addRow(
            self.tr("Native format:"),
            QLabel(
                self.tr("{} channel(s), {} Hz").format(
                    self.native_channels, self.native_fs
                )
            ),
        )
        layout.addLayout(info_layout)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        choices_layout = QFormLayout()
        choices_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        choices_layout.addRow(QLabel(self.tr("Open in visualization:")))

        # ------- Channel mode -------
        channel_mode_box = QWidget()
        channel_mode_layout = QHBoxLayout(channel_mode_box)
        channel_mode_layout.setContentsMargins(0, 0, 0, 0)

        self.mono_radio = QRadioButton(self.tr("Mono"))
        self.stereo_radio = QRadioButton(self.tr("Stereo"))
        self.multichannel_radio = QRadioButton(self.tr("Multichannel"))

        self.channel_mode_group = QButtonGroup(self)
        self.channel_mode_group.addButton(self.mono_radio)
        self.channel_mode_group.addButton(self.stereo_radio)
        self.channel_mode_group.addButton(self.multichannel_radio)

        channel_mode_layout.addWidget(self.mono_radio)
        channel_mode_layout.addWidget(self.stereo_radio)
        channel_mode_layout.addWidget(self.multichannel_radio)
        choices_layout.addWidget(channel_mode_box)

        self.stereo_radio.setEnabled(self.native_channels >= 2)
        self.multichannel_radio.setEnabled(self.native_channels > 2)

        if self.native_channels > 2:
            self.multichannel_radio.setChecked(True)
        elif self.native_channels == 2:
            self.stereo_radio.setChecked(True)
        else:
            self.mono_radio.setChecked(True)

        # ------- Primary channel -------
        options_layout = QFormLayout()
        options_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.primary_channel_combo = QComboBox()
        options_layout.addRow(self.tr("Primary channel:"), self.primary_channel_combo)

        choices_layout.addRow(options_layout)
        layout.addLayout(choices_layout)


        self._populate_primary_channel_combo()
        self.channel_mode_group.buttonToggled.connect(
            self._populate_primary_channel_combo
        )

        # ------- Buttons -------
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _current_channel_mode(self) -> str:
        if self.multichannel_radio.isChecked():
            return CHANNEL_MODE_MULTICHANNEL
        if self.stereo_radio.isChecked():
            return CHANNEL_MODE_STEREO
        return CHANNEL_MODE_MONO

    def _retained_channels_for_mode(self, mode: str) -> list[int]:
        if mode == CHANNEL_MODE_STEREO:
            return [0, 1]
        if mode == CHANNEL_MODE_MULTICHANNEL:
            return list(range(self.native_channels))
        return list(range(self.native_channels))  # mono: any channel selectable

    def _populate_primary_channel_combo(self, *_args):
        previous_channel = self.primary_channel_combo.currentData()

        self.primary_channel_combo.clear()
        candidates = self._retained_channels_for_mode(self._current_channel_mode())
        for idx in candidates:
            self.primary_channel_combo.addItem(
                _channel_label(idx, self.native_channels), idx
            )

        if previous_channel in candidates:
            self.primary_channel_combo.setCurrentIndex(candidates.index(previous_channel))

    def build_options(self) -> AudioOpenOptions:
        channel_mode = self._current_channel_mode()
        primary_channel = self.primary_channel_combo.currentData()

        if channel_mode == CHANNEL_MODE_MONO:
            retained_channels = [primary_channel]
        else:
            retained_channels = self._retained_channels_for_mode(channel_mode)

        return AudioOpenOptions(
            target_fs=DEFAULT_SAMPLE_RATE,
            channel_mode=channel_mode,
            retained_channels=retained_channels,
            primary_channel=primary_channel,
        )
