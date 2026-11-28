from pathlib import Path

import pytest
from PyQt6.QtWidgets import QComboBox, QDialog
from pytestqt.qtbot import QtBot

from ui.main.component.open_path_dialog import OpenPathDialog


def make_dialog(qtbot: QtBot, directory: Path) -> OpenPathDialog:
    dialog = OpenPathDialog(None, "Open", str(directory), "Sound files (*.wav)")
    qtbot.addWidget(dialog)
    return dialog


def test_accepts_selected_files(qtbot: QtBot, tmp_path: Path):
    wav = tmp_path / "sound.wav"
    wav.write_bytes(b"")
    dialog = make_dialog(qtbot, tmp_path)
    dialog.selectFile(str(wav))

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selectedFiles() == [str(wav)]


def test_opening_a_directory_shows_what_is_in_it(qtbot: QtBot, tmp_path: Path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    dialog = make_dialog(qtbot, tmp_path)
    dialog.selectFile(str(folder))

    dialog.accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.project_dir is None
    assert dialog.directory().absolutePath() == str(folder)


def test_offers_a_button_to_open_the_folder_as_a_project(qtbot: QtBot, tmp_path: Path):
    dialog = make_dialog(qtbot, tmp_path)

    assert dialog.open_project_btn is not None
    assert dialog.open_project_btn.text() == "Open Folder as Project"


def test_button_chooses_the_folder_being_shown(qtbot: QtBot, tmp_path: Path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    dialog = make_dialog(qtbot, tmp_path)
    dialog.setDirectory(str(folder))

    assert dialog.open_project_btn is not None
    dialog.open_project_btn.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.project_dir == str(folder)


def test_button_chooses_the_selected_folder(qtbot: QtBot, tmp_path: Path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    dialog = make_dialog(qtbot, tmp_path)
    dialog.selectFile(str(folder))

    assert dialog.open_project_btn is not None
    dialog.open_project_btn.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.project_dir == str(folder)


def test_get_paths_returns_the_project_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def fake_exec(self: OpenPathDialog) -> QDialog.DialogCode:
        self.setDirectory(str(tmp_path))
        self.open_folder_as_project()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(OpenPathDialog, "exec", fake_exec)

    assert OpenPathDialog.get_paths(None, "Open", str(tmp_path)) == [str(tmp_path)]


def test_get_paths_returns_the_selected_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    wav = tmp_path / "sound.wav"
    wav.write_bytes(b"")

    def fake_exec(self: OpenPathDialog) -> QDialog.DialogCode:
        self.selectFile(str(wav))
        self.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(OpenPathDialog, "exec", fake_exec)

    assert OpenPathDialog.get_paths(None, "Open", str(tmp_path)) == [str(wav)]


def test_get_paths_is_empty_when_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(
        OpenPathDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )

    assert OpenPathDialog.get_paths(None, "Open", str(tmp_path)) == []


def test_hides_the_file_type_filter(qtbot: QtBot, tmp_path: Path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.show()

    combo = dialog.findChild(QComboBox, "fileTypeCombo")

    assert combo is not None and combo.isHidden()
