from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QAction, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMenu,
    QMessageBox,
    QWidget,
)
from pytestqt.qtbot import QtBot
from support.annotation_repository import SeedableAnnotationRepository
from support.audio_player import FakeAudioPlayer
from support.job_manager import FakeJobManager
from support.mocks import mock_use_case
from support.textgrid import write_simple_textgrid
from support.view_models import (
    StubViewModelFactory,
    make_database_view_model,
    make_main_view_model,
    make_word_import_view_model,
)

import ui.document.document_view as doc_view_module
import ui.main.main_window as main_window_module
from core.annotation.entity.annotation import AnnotationLabel, AnnotationType
from core.import_metadata.entity.information_source import InformationSource
from core.import_metadata.information_sources_file import SaveInformationSource
from core.load_audio.entity.audio_signal import AudioSignal
from core.project_layout.project_layout_file import SaveProjectLayout
from core.save_audio.save_audio import SaveAudio
from core.settings.app_settings import settings
from data.annotation.datasource.annotation_datasource import AnnotationDataSource
from data.annotation.repository.annotation_repository import DataAnnotationRepository
from data.base.database import SQLiteDatabase
from phonlab_project.layout.project_layout import ChannelRole, ProjectLayout
from phonlab_project.metadata import MetadataTarget
from ui.annotation.annotation_plot import AnnotationPlot
from ui.annotation.component.tier_display_dialog import TierDisplayDialog
from ui.annotation.component.tier_font_dialog import TierFontDialog
from ui.annotation.component.tier_search_dialog import TierSearchDialog
from ui.annotation.state.arrange_tiers_state import ArrangeTiersAction
from ui.annotation.state.tier_display_state import TierDisplayState
from ui.annotation.state.tier_search_state import (
    TierLabelsChangedState,
    TierSearchAction,
    TierSearchMatchState,
)
from ui.document.document_view import DocumentView
from ui.document.document_view_model import DocumentViewModel
from ui.document.state.audio_channel_state import AudioChannelState, AudioState
from ui.document.state.plot_layout_state import PlotType
from ui.main.component.add_to_project_dialog import (
    NEW_ANNOTATIONS,
    REPLACEMENT_ANNOTATIONS,
    TALKERS,
    WORDS,
    AddToProjectDialog,
)
from ui.main.component.open_audio_dialog import OpenAudioDialog
from ui.main.component.open_path_dialog import OpenPathDialog
from ui.main.component.save_audio_dialog import SaveOptions
from ui.main.main_view_model import MainViewModel
from ui.main.main_window import MainWindow
from ui.main.state.audio_open_options import AudioOpenOptionsState
from ui.main.state.openable_file import OpenableFile
from ui.metadata_import.metadata_import_dialog import MetadataImportDialog
from ui.project_layout.project_layout_dialog import ProjectLayoutDialog
from ui.word_import.word_import_dialog import WordImportDialog


@pytest.fixture(autouse=True)
def disable_zero_crossing_snapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "cut_and_paste_at_zero_crossings", False)


@pytest.fixture(autouse=True)
def accept_layout_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> list[ProjectLayoutDialog]:
    """The dialog that asks how a new project is organized answers "Use This Layout"
    at once; the dialogs shown are returned"""
    shown: list[ProjectLayoutDialog] = []

    def exec_(self: ProjectLayoutDialog) -> int:
        shown.append(self)
        self.accept_layout()
        return self.result()

    monkeypatch.setattr(ProjectLayoutDialog, "exec", exec_)
    return shown


@pytest.fixture
def save_audio() -> SaveAudio:
    return mock_use_case(SaveAudio)


@pytest.fixture
def project_repository() -> SeedableAnnotationRepository:
    """The project database behind `main_window`"""
    return SeedableAnnotationRepository()


@pytest.fixture
def main_window(
    qtbot: QtBot,
    fake_audio_player: type[FakeAudioPlayer],
    fake_job_manager: type[FakeJobManager],
    save_audio: SaveAudio,
    project_repository: SeedableAnnotationRepository,
) -> MainWindow:
    win = MainWindow(
        StubViewModelFactory(
            {MainViewModel: make_main_view_model(project_repository)},
            save_audio=save_audio,
        )
    )
    qtbot.addWidget(win)
    return win


def add_document(main_window: MainWindow, name: str = "doc.wav") -> DocumentView:
    vm = main_window.view_model_factory.create(DocumentViewModel)
    doc = DocumentView(vm)
    doc.origin_name = name
    doc.origin_path = f"/tmp/{name}"
    main_window.tab_widget.addTab(doc, name)
    main_window.tab_widget.setCurrentIndex(main_window.tab_widget.count() - 1)
    return doc


def load_signal(doc: DocumentView, x: np.ndarray, fs: int):
    doc.view_model.set_audio(
        AudioState({0: AudioChannelState(np.asarray(x, dtype=np.float64), fs)}),
        primary_channel_idx=0,
        reset_window=True,
    )


# --------------------------- basic construction ---------------------------


def test_starts_with_no_tabs_and_disabled_spectrogram_action(main_window: MainWindow):
    assert main_window.tab_widget.count() == 0
    assert main_window.sgramview_action.isEnabled() is False


def test_get_current_document_is_none_without_tabs(main_window: MainWindow):
    assert main_window.get_current_document() is None


def test_get_current_document_returns_active_tab(main_window: MainWindow):
    doc = add_document(main_window)

    assert main_window.get_current_document() is doc


# --------------------------- open_files ---------------------------


def test_open_files_creates_a_tab_and_loads_audio(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )

    main_window.open_files([("sound", str(wav_path), None)], str(tmp_path))

    assert main_window.tab_widget.count() == 1
    assert main_window.tab_widget.tabText(0) == "sound.wav"
    doc = main_window.get_current_document()
    assert doc.origin_name == "sound.wav"
    assert doc.origin_path == str(wav_path)
    assert "load_audio" in doc.view_model.job_managers


def test_open_files_also_loads_a_paired_textgrid(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    textgrid_path = tmp_path / "sound.TextGrid"
    textgrid_path.write_text(
        'File type = "ooTextFile"\n'
        'Object class = "TextGrid"\n'
        "xmin = 0\nxmax = 1.0\n"
        "tiers? <exists>\nsize = 1\nitem []:\n"
        "    item [1]:\n"
        '        class = "IntervalTier"\n'
        '        name = "word"\n'
        "        xmin = 0\nxmax = 1.0\n"
        "        intervals: size = 1\n"
        "        intervals [1]:\n"
        "            xmin = 0\nxmax = 1.0\n"
        '            text = "hi"\n'
    )
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )

    main_window.open_files(
        [("sound", str(wav_path), str(textgrid_path))], str(tmp_path)
    )

    doc = main_window.get_current_document()
    annotation_view_model = doc.view_model.annotation_view_model
    job = annotation_view_model.job_managers["parse_textgrid"].jobs[0]
    job.on_success(next(job.task))
    assert {
        node.x for node in annotation_view_model.annotation_state.nodes.values()
    } == {0.0, 1.0}


def stub_overwrite_scenario(
    monkeypatch: pytest.MonkeyPatch,
    has_annotation: bool,
    *answers: QMessageBox.StandardButton,
) -> tuple[list, list]:
    """Every document reports `has_annotation`; returns the (path, overwrite) calls to
    `load_textgrid` and the TextGrid names the user was asked about"""
    loaded: list = []
    asked: list = []
    remaining = list(answers)
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )
    monkeypatch.setattr(
        DocumentViewModel, "has_annotation", lambda self: has_annotation
    )
    monkeypatch.setattr(
        DocumentView,
        "load_textgrid",
        lambda self, path, overwrite=False: loaded.append((Path(path).name, overwrite)),
    )

    def question(
        parent: object, title: str, text: str, *args: object, **kwargs: object
    ) -> QMessageBox.StandardButton:
        asked.append(text)
        return remaining.pop(0)

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return loaded, asked


def paired_files(tmp_path: Path, *stems: str) -> list[tuple[str, str, str]]:
    return [
        (stem, str(tmp_path / f"{stem}.wav"), str(tmp_path / f"{stem}.TextGrid"))
        for stem in stems
    ]


def test_open_files_loads_textgrid_without_asking_when_database_is_empty(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    loaded, asked = stub_overwrite_scenario(monkeypatch, False)

    main_window.open_files(paired_files(tmp_path, "a"), str(tmp_path))

    assert loaded == [("a.TextGrid", False)]
    assert asked == []


def test_open_files_overwrites_existing_annotation_when_user_says_yes(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.Yes
    )

    main_window.open_files(paired_files(tmp_path, "a"), str(tmp_path))

    assert loaded == [("a.TextGrid", True)]
    assert asked == ["Overwrite the existing database with annotation from a.TextGrid?"]


def test_open_files_skips_textgrid_when_user_says_no(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes
    )

    main_window.open_files(paired_files(tmp_path, "a", "b"), str(tmp_path))

    assert loaded == [("b.TextGrid", True)]
    assert len(asked) == 2


def test_open_files_asks_once_and_overwrites_all_on_yes_to_all(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.YesToAll
    )

    main_window.open_files(paired_files(tmp_path, "a", "b"), str(tmp_path))

    assert loaded == [("a.TextGrid", True), ("b.TextGrid", True)]
    assert len(asked) == 1


def test_open_files_asks_once_and_skips_all_on_no_to_all(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.NoToAll
    )

    main_window.open_files(paired_files(tmp_path, "a", "b"), str(tmp_path))

    assert loaded == []
    assert len(asked) == 1


def test_open_files_does_nothing_when_dialog_is_cancelled(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog, "get_options", staticmethod(lambda filename, parent=None: None)
    )

    main_window.open_files([("sound", str(wav_path), None)], str(tmp_path))

    assert main_window.tab_widget.count() == 0


def test_open_single_document_raises_without_a_wav_file(
    main_window: MainWindow, tmp_path: Path
):
    textgrid_path = tmp_path / "only.TextGrid"
    textgrid_path.write_text("")

    with pytest.raises(ValueError):
        main_window.open_single_document([str(textgrid_path)])

    assert main_window.tab_widget.count() == 0


def test_open_files_closes_splash_screen(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )
    closed = []
    main_window.splash = type(
        "FakeSplash", (), {"close": lambda self: closed.append(True)}
    )()

    main_window.open_files([("sound", str(wav_path), None)], str(tmp_path))

    assert closed == [True]
    assert main_window.splash is None


def test_save_textgrid_opens_dialog_on_current_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window)
    calls = []
    monkeypatch.setattr(doc, "open_save_textgrid", lambda: calls.append(True))

    main_window.save_textgrid()

    assert calls == [True]


def test_save_textgrid_does_nothing_without_a_document(main_window: MainWindow):
    main_window.save_textgrid()

    assert main_window.tab_widget.count() == 0


# --------------------------- opening projects and documents ---------------------------


@pytest.fixture
def opened(main_window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> list:
    """Records the `open_files` calls instead of creating tabs"""
    calls: list = []
    monkeypatch.setattr(
        main_window,
        "open_files",
        lambda files, dir_path: calls.append((files, dir_path)),
    )
    return calls


def patch_open_dialog(monkeypatch: pytest.MonkeyPatch, *selections: list[str]):
    """Answers each open dialog with the next selection: a directory or files"""
    remaining = list(selections)
    monkeypatch.setattr(
        OpenPathDialog,
        "get_paths",
        staticmethod(lambda *args, **kwargs: remaining.pop(0)),
    )


def patch_directory_dialog(monkeypatch: pytest.MonkeyPatch, *answers: str):
    """Answers each open dialog with a directory, or cancels when it is ''"""
    patch_open_dialog(monkeypatch, *([answer] if answer else [] for answer in answers))


patch_file_dialog = patch_open_dialog


def test_select_project_does_nothing_when_dialog_is_cancelled(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, opened: list
):
    patch_directory_dialog(monkeypatch, "")

    main_window.select_path_to_open()

    assert opened == []


class FakeSplash:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_the_splash_card_goes_away_once_something_is_chosen_to_open(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    splash = FakeSplash()
    main_window.splash = splash  # type: ignore[assignment]
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)

    main_window.select_path_to_open()

    assert splash.closed is True and main_window.splash is None


def test_the_splash_card_stays_when_the_open_dialog_is_cancelled(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, opened: list
):
    splash = FakeSplash()
    main_window.splash = splash  # type: ignore[assignment]
    patch_directory_dialog(monkeypatch, "")

    main_window.select_path_to_open()

    assert splash.closed is False and main_window.splash is splash


def run_import_job(main_window: MainWindow):
    """Runs the recorded project import job synchronously, as the worker would"""
    job = main_window.view_model.job_managers["project_import"].jobs[0]
    for result in job.task:
        job.on_success(result)


def make_project(tmp_path: Path, *names: str, database: bool = False) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "phonlab.toml").write_text("")
    for name in names:
        if name.lower().endswith(".textgrid"):
            write_simple_textgrid(tmp_path / name)
        else:
            (tmp_path / name).write_bytes(b"")
    if database:
        (tmp_path / "phonlab.db").write_bytes(b"")
    return tmp_path


def test_select_project_builds_database_from_textgrids_before_opening_files(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    messages = capture_information(monkeypatch)

    main_window.select_path_to_open()

    assert opened == []  # still importing
    run_import_job(main_window)
    assert messages == ["Found 1 annotation files and built the project database."]
    [(files, dir_path)] = opened
    assert dir_path == str(tmp_path)
    # Annotations come from the database, so no TextGrid is passed on to be read
    assert sorted(files) == [
        OpenableFile("a", str(tmp_path / "a.wav"), None),
        OpenableFile("b", str(tmp_path / "b.wav"), None),
    ]
    assert sorted(project_repository.filenames.values()) == ["a", "b"]
    a = project_repository.find_annotation_by_file_stem("a")
    assert a is not None and [type.type for type in a.types] == ["word"]


@pytest.mark.parametrize("marker", ["phonlab.toml", "phonlab.db"])
def test_opening_a_project_file_opens_its_folder_as_a_project(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    project_repository: SeedableAnnotationRepository,
    marker: str,
):
    make_project(tmp_path, "a.wav", database=True)
    patch_open_dialog(monkeypatch, [str(tmp_path / marker)])

    main_window.select_path_to_open()

    assert opened == [
        ([OpenableFile("a", str(tmp_path / "a.wav"), None)], str(tmp_path))
    ]


def test_the_open_dialog_lists_project_files(main_window: MainWindow):
    assert "phonlab.toml" in main_window.filters
    assert "phonlab.db" in main_window.filters


def test_select_project_with_existing_database_opens_without_reading_textgrids(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", database=True)
    patch_directory_dialog(monkeypatch, str(tmp_path))

    main_window.select_path_to_open()

    assert opened == [
        ([OpenableFile("a", str(tmp_path / "a.wav"), None)], str(tmp_path))
    ]
    assert "project_import" not in main_window.view_model.job_managers
    assert project_repository.filenames == {}


def test_select_project_treats_extensions_case_insensitively(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(
        tmp_path,
        "lower.wav",
        "upper.WAV",
        "mixed.Wav",
        "notes.wav.txt",
        database=True,
    )
    patch_directory_dialog(monkeypatch, str(tmp_path))

    main_window.select_path_to_open()

    [(files, _)] = opened
    assert sorted(file.file_stem for file in files) == ["lower", "mixed", "upper"]


def test_select_project_reads_textgrid_with_any_case_suffix_on_first_open(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.textgrid")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)

    main_window.select_path_to_open()
    run_import_job(main_window)

    a = project_repository.find_annotation_by_file_stem("a")
    assert a is not None and len(a.types) == 1


def test_select_project_reports_unreadable_textgrid_and_still_opens(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav")
    (tmp_path / "a.TextGrid").write_text("not a textgrid")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text, *a: warnings.append(text)),
    )

    main_window.select_path_to_open()
    run_import_job(main_window)

    [warning] = warnings
    assert warning.splitlines() == [
        "Found 1 annotation files and built the project database.",
        "Could not read the annotation file for: a",
    ]
    assert len(opened) == 1


def test_select_project_shows_reading_progress_while_building_the_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav", "b.TextGrid")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)
    main_window.select_path_to_open()
    job = main_window.view_model.job_managers["project_import"].jobs[0]
    results = iter(job.task)

    job.on_success(next(results))  # the project's files are being looked through

    dialog = main_window.progress_dialog
    assert dialog is not None
    assert dialog.windowTitle() == "Importing the project database"
    assert dialog.labelText() == "Looking through the project's files…"
    for _ in range(3):  # registered, TextGrids counted, first one about to be read
        job.on_success(next(results))
    assert dialog.maximum() == 2
    assert dialog.labelText() == (
        "Reading annotations: 0 of 2 done\nNow reading a.TextGrid"
    )
    for result in results:
        job.on_success(result)
        if main_window.progress_dialog is not None:
            # the label keeps its height between files, so the next name has room
            assert main_window.progress_dialog.labelText().count("\n") == 1
    assert main_window.progress_dialog is None
    assert len(opened) == 1


def test_select_project_reports_nothing_when_it_has_no_textgrids(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    messages = capture_information(monkeypatch)

    main_window.select_path_to_open()
    run_import_job(main_window)

    assert messages == []
    assert len(opened) == 1


def test_select_project_does_not_open_files_when_import_fails(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text, *a: warnings.append(text)),
    )

    main_window.select_path_to_open()
    job = main_window.view_model.job_managers["project_import"].jobs[0]
    job.on_error(RuntimeError("disk full"))

    assert opened == []
    assert len(warnings) == 1 and "disk full" in warnings[0]


def test_select_project_initializes_toml_when_user_agrees(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    patch_directory_dialog(monkeypatch, str(tmp_path))
    questions: list[str] = []

    def question(
        parent: object, title: str, text: str, *args: object
    ) -> QMessageBox.StandardButton:
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))

    main_window.select_path_to_open()
    run_import_job(main_window)

    assert questions == ["Make a project out of this folder?"]
    assert (tmp_path / "phonlab.toml").is_file()
    assert opened == [([], str(tmp_path))]


def test_open_single_document_accepts_uppercase_wav(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    wav = str(tmp_path / "sound.WAV")

    main_window.open_single_document([wav], str(tmp_path))

    assert opened == [([("sound", wav, None)], str(tmp_path))]


def test_select_project_asks_again_when_user_declines_initializing(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    patch_directory_dialog(monkeypatch, str(tmp_path), "")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    main_window.select_path_to_open()

    assert not (tmp_path / "phonlab.toml").exists()
    assert opened == []


def test_open_single_document_uses_absolute_stem_without_dir(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    wav = str(tmp_path / "sound.wav")

    main_window.open_single_document([wav])

    assert opened == [([(str(tmp_path / "sound"), wav, None)], None)]


def test_open_single_document_uses_relative_stem_within_dir(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    wav = str(tmp_path / "sound.wav")
    textgrid = str(tmp_path / "sound.TextGrid")

    main_window.open_single_document([wav, textgrid], str(tmp_path))

    assert opened == [([("sound", wav, textgrid)], str(tmp_path))]


def test_open_single_document_raises_for_more_than_one_wav(
    main_window: MainWindow, opened: list
):
    with pytest.raises(ValueError):
        main_window.open_single_document(["a.wav", "b.wav"])

    assert opened == []


def test_select_files_does_nothing_when_dialog_is_cancelled(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, opened: list
):
    patch_file_dialog(monkeypatch, [])

    main_window.select_path_to_open()

    assert opened == []


def test_select_files_opens_selected_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, opened: list
):
    patch_file_dialog(monkeypatch, ["/data/sound.wav"])

    main_window.select_path_to_open()

    assert opened == [([("/data/sound", "/data/sound.wav", None)], None)]


def test_select_files_reports_invalid_selection_and_asks_again(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, opened: list
):
    patch_file_dialog(monkeypatch, ["only.TextGrid"], [])
    messages: list = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: messages.append(args)),
    )

    main_window.select_path_to_open()

    assert len(messages) == 1
    assert opened == []


def test_select_path_starts_in_current_project_dir(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    main_window.view_model.set_dir_path("/project")
    directories: list = []

    def get_paths(
        parent: QWidget | None, caption: str, directory: str | None, filter: str
    ) -> list[str]:
        directories.append(directory)
        return []

    monkeypatch.setattr(OpenPathDialog, "get_paths", staticmethod(get_paths))

    main_window.select_path_to_open()

    assert directories == ["/project"]


# --------------------------- closing the project ---------------------------


@pytest.fixture
def closed_databases(main_window: MainWindow) -> list[str]:
    """The project directories whose database was closed"""
    closed: list[str] = []
    main_window.view_model.close_project_database = closed.append
    return closed


def add_project_document(
    main_window: MainWindow, dir_path: Path, stem: str = "a"
) -> DocumentView:
    vm = main_window.view_model_factory.create(DocumentViewModel, stem, str(dir_path))
    doc = DocumentView(vm)
    main_window.tab_widget.addTab(doc, f"{stem}.wav")
    return doc


def test_opening_a_project_closes_every_open_tab_and_the_open_project(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    closed_databases: list[str],
):
    first = make_project(tmp_path / "first", "a.wav", database=True)
    second = make_project(tmp_path / "second", "b.wav", database=True)
    main_window.view_model.set_dir_path(str(first))
    add_project_document(main_window, first)
    add_document(main_window, "other.wav")
    patch_open_dialog(monkeypatch, [str(second)])

    main_window.select_path_to_open()

    assert closed_databases == [str(first)]
    assert main_window.tab_widget.count() == 0
    assert main_window.view_model.dir_path == str(second)
    assert opened == [([OpenableFile("b", str(second / "b.wav"), None)], str(second))]


def test_opening_a_project_closes_a_document_opened_on_its_own(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    project = make_project(tmp_path / "project", "a.wav", database=True)
    add_document(main_window, "single.wav")
    patch_open_dialog(monkeypatch, [str(project)])

    main_window.select_path_to_open()

    assert main_window.tab_widget.count() == 0


def test_declining_to_initialize_a_project_keeps_the_open_project(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    closed_databases: list[str],
):
    first = make_project(tmp_path / "first", "a.wav", database=True)
    (tmp_path / "empty").mkdir()
    main_window.view_model.set_dir_path(str(first))
    doc = add_project_document(main_window, first)
    patch_open_dialog(monkeypatch, [str(tmp_path / "empty")], [])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    main_window.select_path_to_open()

    assert closed_databases == []
    assert main_window.documents() == [doc]
    assert main_window.view_model.dir_path == str(first)


def test_opening_a_sound_file_outside_the_project_closes_the_project(
    main_window: MainWindow,
    tmp_path: Path,
    opened: list,
    closed_databases: list[str],
):
    project = make_project(tmp_path / "project", "a.wav", database=True)
    main_window.view_model.set_dir_path(str(project))
    add_project_document(main_window, project)
    main_window.save_layout_action.setEnabled(True)
    main_window.tier_search_dialog = type(
        "FakeDialog", (), {"close": lambda self: None}
    )()  # type: ignore[assignment]
    outside = str(tmp_path / "elsewhere.wav")

    main_window.open_single_document([outside], str(project))

    assert closed_databases == [str(project)]
    assert main_window.documents() == []
    assert main_window.view_model.dir_path is None
    assert main_window.tier_search_dialog is None
    assert main_window.save_layout_action.isEnabled() is False
    assert not main_window.add_files_action.isEnabled()
    assert opened == [([(str(tmp_path / "elsewhere"), outside, None)], None)]


def test_opening_a_sound_file_in_the_project_keeps_the_project_open(
    main_window: MainWindow,
    tmp_path: Path,
    opened: list,
    closed_databases: list[str],
):
    project = make_project(tmp_path, "a.wav", database=True)
    main_window.view_model.set_dir_path(str(project))
    doc = add_project_document(main_window, project)
    wav = str(project / "sub" / "b.wav")

    main_window.open_single_document([wav], str(project))

    assert closed_databases == []
    assert main_window.documents() == [doc]
    assert opened == [([("sub/b", wav, None)], str(project))]


def test_invalid_selection_keeps_the_project_open(
    main_window: MainWindow, tmp_path: Path, closed_databases: list[str]
):
    main_window.view_model.set_dir_path(str(tmp_path))

    with pytest.raises(ValueError):
        main_window.open_single_document([str(tmp_path / "a.TextGrid")], str(tmp_path))

    assert closed_databases == []
    assert main_window.view_model.dir_path == str(tmp_path)


def test_close_project_without_a_project_does_nothing(
    main_window: MainWindow, closed_databases: list[str]
):
    doc = add_document(main_window)

    main_window.close_project()

    assert closed_databases == []
    assert main_window.documents() == [doc]


def test_open_paths_opens_a_lone_directory_as_a_project(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    make_project(tmp_path, "a.wav", database=True)

    main_window.open_paths([str(tmp_path)])

    assert opened == [
        ([OpenableFile("a", str(tmp_path / "a.wav"), None)], str(tmp_path))
    ]


def test_open_paths_opens_sound_files_as_a_document(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    wav = str(tmp_path / "sound.wav")

    main_window.open_paths([wav])

    assert opened == [([(str(tmp_path / "sound"), wav, None)], None)]


# --------------------------- copy/cut open a clip tab ---------------------------


def test_copy_selection_opens_a_clip_tab_and_sets_clipboard(main_window: MainWindow):
    doc = add_document(main_window, "source.wav")
    load_signal(doc, np.arange(10000), fs=1000)
    doc.view_model.start_selection(2.0)
    doc.view_model.continue_selection(3.0)

    main_window.copy_selection()

    assert main_window.tab_widget.count() == 2
    assert main_window.tab_widget.tabText(1) == "CLIP 1: source.wav"
    assert main_window.clipboard is not None
    assert len(main_window.clipboard.channels[0].x) == 1000


def test_cut_selection_opens_a_clip_tab_and_sets_clipboard(main_window: MainWindow):
    doc = add_document(main_window, "source.wav")
    load_signal(doc, np.arange(10000), fs=1000)
    doc.view_model.start_selection(2.0)
    doc.view_model.continue_selection(3.0)

    main_window.cut_selection()

    assert main_window.tab_widget.count() == 2
    assert main_window.clipboard is not None
    assert len(doc.view_model.primary_channel().x) == 9000


def test_repeated_clips_from_same_source_increment_clip_counter(
    main_window: MainWindow,
):
    doc = add_document(main_window, "source.wav")
    load_signal(doc, np.arange(10000), fs=1000)
    doc.view_model.start_selection(1.0)
    doc.view_model.continue_selection(2.0)
    main_window.copy_selection()

    main_window.tab_widget.setCurrentWidget(doc)
    doc.view_model.start_selection(3.0)
    doc.view_model.continue_selection(4.0)
    main_window.copy_selection()

    assert main_window.tab_widget.tabText(1) == "CLIP 1: source.wav"
    assert main_window.tab_widget.tabText(2) == "CLIP 2: source.wav"


def test_copy_selection_does_nothing_without_a_selection(main_window: MainWindow):
    doc = add_document(main_window, "source.wav")
    load_signal(doc, np.arange(10000), fs=1000)

    main_window.copy_selection()

    assert main_window.tab_widget.count() == 1
    assert main_window.clipboard is None


# --------------------------- tab lifecycle ---------------------------


def test_close_tab_cleans_up_and_removes_it(main_window: MainWindow):
    doc = add_document(main_window)

    main_window.close_tab(0)

    assert main_window.tab_widget.count() == 0
    assert doc.view_model.audio_player.stopped is True


def test_close_current_tab_closes_the_active_tab(main_window: MainWindow):
    add_document(main_window, "a.wav")
    add_document(main_window, "b.wav")

    main_window.close_current_tab()

    assert main_window.tab_widget.count() == 1
    assert main_window.tab_widget.tabText(0) == "a.wav"


def test_close_current_tab_is_a_noop_without_tabs(main_window: MainWindow):
    main_window.close_current_tab()

    assert main_window.tab_widget.count() == 0


def test_on_tab_changed_enables_spectrogram_action_when_prepped(
    main_window: MainWindow,
):
    doc = add_document(main_window)
    doc.view_model.spectrogram_view_model.prepped_audio_state = object()

    main_window.on_tab_changed(0)

    assert main_window.sgramview_action.isEnabled() is True


def test_on_tab_changed_disables_spectrogram_action_when_not_prepped(
    main_window: MainWindow,
):
    add_document(main_window)

    main_window.on_tab_changed(0)

    assert main_window.sgramview_action.isEnabled() is False


# --------------------------- display plan ---------------------------


def test_switching_tabs_applies_the_current_display_plan(main_window: MainWindow):
    first = add_document(main_window, "first.wav")
    add_document(main_window, "second.wav")  # the current tab
    main_window.view_model.set_display_plan({PlotType.WAVEFORM, PlotType.SPECTROGRAM})

    main_window.tab_widget.setCurrentWidget(first)

    assert PlotType.SPECTROGRAM in first.view_model.plot_layout_state.plots


def test_toggling_a_plot_updates_the_display_plan(main_window: MainWindow):
    doc = add_document(main_window)
    doc.view_model.set_audio(
        AudioState({0: AudioChannelState(np.zeros(2000), 1000)}),
        primary_channel_idx=0,
        reset_window=True,
    )
    doc.view_model.update_spectrogram = lambda: None

    main_window.plot_wave_sgram()

    assert settings.display_plan == ["waveform", "spectrogram"]


def test_save_layout_action_needs_a_project(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    assert main_window.save_layout_action.isEnabled() is False
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )

    main_window.open_files([("sound", str(wav_path), None)], str(tmp_path))

    assert main_window.save_layout_action.isEnabled() is True


def test_save_window_layout_saves_the_plan_to_the_project(main_window: MainWindow):
    save = main_window.view_model.save_display_plan_use_case
    main_window.view_model.set_dir_path("/some/dir")
    main_window.view_model.set_display_plan({PlotType.WAVEFORM, PlotType.SPECTROGRAM})

    main_window.save_window_layout()

    assert save.call_args.args == (["waveform", "spectrogram"], "/some/dir")


def test_save_window_layout_reports_a_failed_save(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    main_window.view_model.set_dir_path("/some/dir")
    main_window.view_model.save_display_plan_use_case.side_effect = OSError("denied")
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args: errors.append(args))
    )

    main_window.save_window_layout()

    assert len(errors) == 1


def test_a_new_document_starts_with_the_display_plan(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    wav_path = tmp_path / "sound.wav"
    wav_path.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda filename, parent=None: AudioOpenOptionsState()),
    )
    main_window.view_model.set_display_plan({PlotType.WAVEFORM, PlotType.ANNOTATION})

    main_window.open_files([("sound", str(wav_path), None)], None)

    doc = main_window.get_current_document()
    assert doc.view_model.plot_layout_state.plots == {
        PlotType.WAVEFORM,
        PlotType.ANNOTATION,
    }


# --------------------------- delegation to current document ---------------------------


@pytest.mark.parametrize(
    "action,doc_method",
    [
        (lambda w: w.plot_wave(), "toggle_wave"),
        (lambda w: w.plot_wave_sgram(), "toggle_spectrogram"),
        (lambda w: w.plot_annotations(), "toggle_annotations"),
        (lambda w: w.show_all(), "show_all"),
        (lambda w: w.play_visible(), "play_visible"),
        (lambda w: w.stop_audio(), "stop_audio"),
        (lambda w: w.recenter_on_selection(), "recenter_on_selection"),
        (lambda w: w.undo(), "undo"),
        (lambda w: w.redo(), "redo"),
    ],
)
def test_delegates_to_current_document(
    main_window: MainWindow, action: Callable[[MainWindow], None], doc_method: str
):
    doc = add_document(main_window)
    calls = []
    setattr(doc, doc_method, lambda: calls.append(True))

    action(main_window)

    assert calls == [True]


@pytest.mark.parametrize(
    "action",
    [
        lambda w: w.plot_wave(),
        lambda w: w.show_all(),
        lambda w: w.play_visible(),
        lambda w: w.undo(),
        lambda w: w.redo(),
    ],
)
def test_delegation_is_a_noop_without_a_current_document(
    main_window: MainWindow, action: Callable[[MainWindow], None]
):
    # Should not raise even though there is no active document.
    action(main_window)


def test_paste_at_cursor_forwards_clipboard_to_document(main_window: MainWindow):
    doc = add_document(main_window)
    calls = []
    doc.paste_at_cursor = lambda clip: calls.append(clip)
    main_window.clipboard = AudioSignal(np.array([1.0, 2.0]), 1000)

    main_window.paste_at_cursor()

    assert len(calls) == 1
    assert calls[0] is main_window.clipboard


def test_paste_at_cursor_does_nothing_without_a_clipboard(main_window: MainWindow):
    doc = add_document(main_window)
    calls = []
    doc.paste_at_cursor = lambda clip: calls.append(clip)

    main_window.paste_at_cursor()

    assert calls == []


def test_paste_special_forwards_clipboard_to_document(main_window: MainWindow):
    doc = add_document(main_window)
    calls = []
    doc.paste_special = lambda clip: calls.append(clip)
    main_window.clipboard = AudioSignal(np.array([1.0, 2.0]), 1000)

    main_window.paste_special()

    assert len(calls) == 1
    assert calls[0] is main_window.clipboard


def test_paste_special_does_nothing_without_a_clipboard(main_window: MainWindow):
    doc = add_document(main_window)
    calls = []
    doc.paste_special = lambda clip: calls.append(clip)

    main_window.paste_special()

    assert calls == []


# --------------------------- keyboard navigation ---------------------------


@pytest.mark.parametrize(
    "key,doc_method",
    [
        (Qt.Key.Key_Left, "go_back"),
        (Qt.Key.Key_Right, "advance"),
        (Qt.Key.Key_Down, "zoom_out"),
        (Qt.Key.Key_Up, "zoom_in"),
    ],
)
def test_key_press_forwards_navigation_to_current_document(
    main_window: MainWindow, key: Qt.Key, doc_method: str
):
    doc = add_document(main_window)
    calls = []
    setattr(doc, doc_method, lambda: calls.append(True))
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)

    main_window.keyPressEvent(event)

    assert calls == [True]


def test_key_press_for_unhandled_key_does_not_touch_document(main_window: MainWindow):
    doc = add_document(main_window)
    calls = []
    doc.go_back = lambda: calls.append(True)
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier
    )

    main_window.keyPressEvent(event)

    assert calls == []


# --------------------------- save / info dialogs ---------------------------


def file_menu_actions(main_window: MainWindow) -> dict[str, QAction]:
    menu_bar = main_window.menuBar()
    file_menu = next(a.menu() for a in menu_bar.actions() if a.text() == "&File")
    return {a.text(): a for a in file_menu.actions() if not a.isSeparator()}


def test_file_menu_offers_save_audio_and_the_annotation_menu_exports_annotation(
    main_window: MainWindow,
):
    actions = file_menu_actions(main_window)

    assert actions["Save &Audio…"] is main_window.save_audio_action
    assert "&Export Annotation…" not in actions
    assert main_window.save_audio_action is not main_window.export_annotation_action


def test_save_menu_items_open_their_own_dialogs(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window)
    calls = []
    monkeypatch.setattr(
        main_window_module.SaveAudioDialog,
        "get_options",
        staticmethod(lambda doc, name, parent=None: calls.append("audio")),
    )
    doc.open_save_textgrid = lambda: calls.append("textgrid")

    main_window.save_audio_action.trigger()
    main_window.export_annotation_action.trigger()

    assert calls == ["audio", "textgrid"]


def test_save_menu_item_has_the_standard_save_shortcut(main_window: MainWindow):
    assert main_window.save_audio_action.shortcut() == QKeySequence.StandardKey.Save


def test_save_audio_invokes_save_use_case_with_selected_options(
    main_window: MainWindow, save_audio: SaveAudio, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window, "myfile.wav")
    load_signal(doc, np.arange(5000), fs=1000)
    monkeypatch.setattr(
        main_window_module.SaveAudioDialog,
        "get_options",
        staticmethod(
            lambda doc, name, parent=None: SaveOptions(
                path="/tmp/out.wav", target_fs=8000, scale=True, channels=[0]
            )
        ),
    )

    main_window.save_audio()

    save_audio.assert_called_once()
    path, channels, target_fs, scale = save_audio.call_args.args
    assert (path, channels[0].fs, target_fs, scale) == (
        "/tmp/out.wav",
        1000,
        8000,
        True,
    )


def test_save_audio_does_nothing_without_a_current_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    calls = []
    monkeypatch.setattr(
        main_window_module.SaveAudioDialog,
        "get_options",
        staticmethod(lambda doc, name, parent=None: calls.append(True)),
    )

    main_window.save_audio()

    assert calls == []


def test_save_audio_shows_error_dialog_on_failure(
    main_window: MainWindow, save_audio: SaveAudio, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window, "myfile.wav")
    load_signal(doc, np.arange(5000), fs=1000)
    monkeypatch.setattr(
        main_window_module.SaveAudioDialog,
        "get_options",
        staticmethod(
            lambda doc, name, parent=None: SaveOptions(
                path="/tmp/out.wav", target_fs=8000, scale=True, channels=[0]
            )
        ),
    )

    save_audio.side_effect = RuntimeError("disk full")
    critical_calls = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: critical_calls.append(True)),
    )

    main_window.save_audio()

    assert critical_calls == [True]


def test_show_audio_info_execs_dialog_for_current_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window, "myfile.wav")
    load_signal(doc, np.arange(5000), fs=1000)
    calls = []
    monkeypatch.setattr(
        doc_view_module.AudioInfoDialog,
        "show_info",
        staticmethod(
            lambda primary_channel, stereo_channels, name, parent=None: calls.append(
                name
            )
        ),
    )

    main_window.show_audio_info()

    assert calls == ["myfile.wav"]


def test_show_audio_info_does_nothing_without_a_current_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    calls = []
    monkeypatch.setattr(
        doc_view_module.AudioInfoDialog,
        "show_info",
        staticmethod(lambda doc, name, parent=None: calls.append(name)),
    )

    main_window.show_audio_info()

    assert calls == []


# --------------------------- shutdown ---------------------------


def test_quit_app_cleans_up_all_documents_and_quits(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc_a = add_document(main_window, "a.wav")
    doc_b = add_document(main_window, "b.wav")
    quit_calls = []
    monkeypatch.setattr(
        QApplication, "quit", staticmethod(lambda: quit_calls.append(True))
    )

    main_window.quit_app()

    assert doc_a.view_model.audio_player.stopped is True
    assert doc_b.view_model.audio_player.stopped is True
    assert quit_calls == [True]


def test_close_event_cleans_up_all_documents_and_accepts(main_window: MainWindow):
    from PyQt6.QtGui import QCloseEvent

    doc = add_document(main_window)
    event = QCloseEvent()

    main_window.closeEvent(event)

    assert doc.view_model.audio_player.stopped is True
    assert event.isAccepted() is True


# --------------------------- project menu ---------------------------


def test_project_actions_are_disabled_until_a_project_is_open(
    main_window: MainWindow, tmp_path: Path
):
    assert not main_window.add_files_action.isEnabled()
    assert not main_window.rebuild_action.isEnabled()

    main_window.view_model.set_dir_path(str(tmp_path))
    main_window.update_project_actions()

    assert main_window.add_files_action.isEnabled()
    assert main_window.rebuild_action.isEnabled()


def test_menus_are_ordered_file_edit_project_annotation_view(main_window: MainWindow):
    titles = [
        action.text().replace("&", "") for action in main_window.menuBar().actions()
    ]

    assert titles == ["File", "Edit", "Project", "Annotation", "View"]


def test_project_menu_lists_the_project_actions(main_window: MainWindow):
    menu = next(
        action.menu()
        for action in main_window.menuBar().actions()
        if action.text().replace("&", "") == "Project"
    )

    assert [action for action in menu.actions() if not action.isSeparator()] == [
        main_window.add_files_action,
        main_window.rebuild_action,
        main_window.project_layout_action,
        main_window.inspect_database_action,
        main_window.save_layout_action,
    ]


def test_save_window_layout_is_in_the_project_menu_not_the_file_menu(
    main_window: MainWindow,
):
    def menu_named(name: str) -> QMenu:
        return next(
            action.menu()
            for action in main_window.menuBar().actions()
            if action.text().replace("&", "") == name
        )

    assert main_window.save_layout_action not in menu_named("File").actions()


def capture_information(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, text, *a: messages.append(text)),
    )
    return messages


def test_add_new_files_asks_what_to_add_and_does_that(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    done: list[str] = []
    for name in (
        "add_new_annotations",
        "replace_annotations",
        "add_talkers",
        "add_words",
    ):
        monkeypatch.setattr(main_window, name, lambda name=name: done.append(name))
    answers = iter([NEW_ANNOTATIONS, REPLACEMENT_ANNOTATIONS, TALKERS, WORDS, None])
    monkeypatch.setattr(
        AddToProjectDialog, "get_choice", staticmethod(lambda parent: next(answers))
    )

    for _ in range(5):
        main_window.add_new_files()

    assert done == [
        "add_new_annotations",
        "replace_annotations",
        "add_talkers",
        "add_words",
    ]  # and nothing when the dialog is cancelled


def test_add_new_annotations_says_when_there_is_nothing_new(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", database=True)
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)
    main_window.add_new_annotations()
    run_import_job(main_window)
    messages.clear()
    main_window.view_model.job_managers.clear()

    main_window.add_new_annotations()
    run_import_job(main_window)

    assert messages == ["There are no new annotations to add."]


def choose_textgrids(monkeypatch: pytest.MonkeyPatch, paths: list[Path]) -> list[str]:
    """Answers the dialog for TextGrids with `paths`, and the question with Yes"""
    questions: list[str] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(p) for p in paths], "")),
    )

    def question(parent: object, title: str, text: str, *a: object):  # noqa: ANN202
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return questions


def test_replacement_annotations_overwrite_the_ones_in_the_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav", "b.TextGrid")
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)
    main_window.add_new_annotations()
    run_import_job(main_window)
    for stem in ("a", "b"):
        repository_id = project_repository.find_annotation_by_file_stem(stem).get_id()  # type: ignore[union-attr]
        project_repository.clear_annotation(repository_id)
        project_repository.create_types(repository_id, [AnnotationType("edited", [])])
    messages.clear()
    main_window.view_model.job_managers.clear()
    questions = choose_textgrids(monkeypatch, [tmp_path / "a.TextGrid"])

    main_window.replace_annotations()
    run_import_job(main_window)

    a = project_repository.find_annotation_by_file_stem("a")
    b = project_repository.find_annotation_by_file_stem("b")
    assert a is not None and [t.type for t in a.types] == ["word"]  # replaced
    assert b is not None and [t.type for t in b.types] == ["edited"]  # not chosen
    assert "1 annotation files" in questions[0]
    assert messages == ["Replaced the annotations for 1 annotation files."]


def test_replacement_says_which_chosen_textgrids_belong_to_no_recording(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "orphan.TextGrid")
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)
    choose_textgrids(
        monkeypatch, [tmp_path / "a.TextGrid", tmp_path / "orphan.TextGrid"]
    )

    main_window.replace_annotations()
    run_import_job(main_window)

    assert (
        messages[0].splitlines()[0]
        == "Replaced the annotations for 1 annotation files."
    )
    assert "1 of the files chosen are not matched with a recording" in messages[0]


def test_replacement_does_nothing_when_no_textgrid_is_chosen_or_it_is_not_confirmed(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], ""))
    )

    main_window.replace_annotations()

    assert "project_import" not in main_window.view_model.job_managers

    choose_textgrids(monkeypatch, [tmp_path / "a.TextGrid"])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )

    main_window.replace_annotations()

    assert "project_import" not in main_window.view_model.job_managers


def test_add_new_files_registers_new_stems_and_reads_textgrids_for_empty_ones(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "old.wav", "new.wav", "new.TextGrid", "old.TextGrid")
    project_repository.create_annotation("old")  # in the database, but empty
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)

    main_window.add_new_annotations()
    run_import_job(main_window)

    assert sorted(project_repository.filenames.values()) == ["new", "old"]
    for stem in ("new", "old"):
        annotation = project_repository.find_annotation_by_file_stem(stem)
        assert annotation is not None and len(annotation.types) == 1
    assert messages == ["Added 1 new files and read 2 annotation files."]


def test_add_new_files_leaves_existing_annotations_alone(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    main_window.view_model.set_dir_path(str(tmp_path))
    capture_information(monkeypatch)
    main_window.add_new_annotations()
    run_import_job(main_window)
    before = project_repository.find_annotation_by_file_stem("a")
    main_window.view_model.job_managers.clear()

    main_window.add_new_annotations()
    run_import_job(main_window)

    assert project_repository.find_annotation_by_file_stem("a") == before


def test_add_new_files_reloads_annotations_of_open_documents(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav")
    main_window.view_model.set_dir_path(str(tmp_path))
    capture_information(monkeypatch)
    reloaded: list[DocumentViewModel] = []
    monkeypatch.setattr(
        DocumentViewModel, "reload_annotation", lambda self: reloaded.append(self)
    )
    first, second = add_document(main_window), add_document(main_window, "two.wav")

    main_window.add_new_annotations()
    run_import_job(main_window)

    assert reloaded == [first.view_model, second.view_model]


def test_add_new_files_reports_unreadable_textgrids(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav")
    (tmp_path / "a.TextGrid").write_text("not a textgrid")
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)

    main_window.add_new_annotations()
    run_import_job(main_window)

    [message] = messages
    assert "Could not read the annotation file for: a" in message


def test_rebuild_project_does_nothing_when_user_declines(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav")
    project_repository.create_annotation("stale")
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    main_window.rebuild_project()

    assert "project_import" not in main_window.view_model.job_managers
    assert list(project_repository.filenames.values()) == ["stale"]


def test_rebuild_project_rereads_textgrids_into_a_new_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    project_repository.create_annotation("stale")
    main_window.view_model.set_dir_path(str(tmp_path))
    questions: list[str] = []

    def question(
        parent: object, title: str, text: str, *args: object
    ) -> QMessageBox.StandardButton:
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    messages = capture_information(monkeypatch)
    reloaded: list[DocumentViewModel] = []
    monkeypatch.setattr(
        DocumentViewModel, "reload_annotation", lambda self: reloaded.append(self)
    )
    doc = add_document(main_window)

    main_window.rebuild_project()
    run_import_job(main_window)

    assert str(tmp_path) in questions[0]
    assert list(project_repository.filenames.values()) == ["a"]
    assert messages == ["The project database has been rebuilt."]
    assert reloaded == [doc.view_model]


def rebuild_a_project_that_remembers_information(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    csv_text: str | None,
) -> list[str]:
    """Rebuilds a project with two talker folders that remembers a talkers CSV file,
    which is written first unless `csv_text` is None. Returns the messages shown"""
    make_project(tmp_path)
    for talker in ("t1", "t2"):
        (tmp_path / talker).mkdir()
        (tmp_path / talker / "a.wav").write_bytes(b"")
        write_simple_textgrid(tmp_path / talker / "a.TextGrid")
    if csv_text is not None:
        (tmp_path / "talkers.csv").write_text(csv_text)
    SaveInformationSource()(
        str(tmp_path),
        InformationSource(
            "talkers.csv", MetadataTarget.TALKER, "talker", {"age": "age"}
        ),
    )
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    messages = capture_information(monkeypatch)

    main_window.rebuild_project()
    run_import_job(main_window)
    return messages


def test_rebuilding_adds_the_remembered_csv_information_to_the_new_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    messages = rebuild_a_project_that_remembers_information(
        main_window, monkeypatch, tmp_path, "talker,age\nt1,31\nt2,45\n"
    )

    assert project_repository.read_metadata(MetadataTarget.TALKER) == {
        "t1": {"age": 31},
        "t2": {"age": 45},
    }
    assert messages == ["The project database has been rebuilt."]


def test_rebuilding_reports_remembered_information_that_cannot_be_added(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    messages = rebuild_a_project_that_remembers_information(
        main_window, monkeypatch, tmp_path, None
    )

    assert project_repository.read_metadata(MetadataTarget.TALKER) == {}
    assert "Could not add the information from talkers.csv" in messages[0]
    assert messages[0].startswith("The project database has been rebuilt.\n")


def add_project_document(
    main_window: MainWindow, tmp_path: Path, file_stem: str = "a"
) -> DocumentView:
    """A tab for a file of the project in tmp_path, as `open_files` creates it"""
    main_window.view_model.set_dir_path(str(tmp_path))
    vm = main_window.view_model_factory.create(
        DocumentViewModel, file_stem, str(tmp_path)
    )
    doc = DocumentView(vm)
    main_window.tab_widget.addTab(doc, f"{file_stem}.wav")
    main_window.tab_widget.setCurrentIndex(main_window.tab_widget.count() - 1)
    return doc


def test_rebuild_annotation_action_needs_a_project_file_in_the_current_tab(
    main_window: MainWindow, tmp_path: Path
):
    assert not main_window.rebuild_annotation_action.isEnabled()

    add_document(main_window)  # a tab that is not a project file
    assert not main_window.rebuild_annotation_action.isEnabled()

    add_project_document(main_window, tmp_path)
    assert main_window.rebuild_annotation_action.isEnabled()

    main_window.tab_widget.setCurrentIndex(0)
    assert not main_window.rebuild_annotation_action.isEnabled()


def test_rebuild_annotation_replaces_the_annotation_with_the_textgrid_when_user_says_yes(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav", "b.TextGrid")
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.Yes
    )
    add_project_document(main_window, tmp_path, "b")

    main_window.rebuild_annotation()

    assert loaded == [("b.TextGrid", True)]
    assert asked == ["Overwrite the existing database with annotation from b.TextGrid?"]


def test_rebuild_annotation_does_nothing_when_user_says_no(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    loaded, asked = stub_overwrite_scenario(
        monkeypatch, True, QMessageBox.StandardButton.No
    )
    add_project_document(main_window, tmp_path)

    main_window.rebuild_annotation()

    assert loaded == []
    assert len(asked) == 1


def test_rebuild_annotation_does_not_ask_when_the_annotation_is_empty(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    loaded, asked = stub_overwrite_scenario(monkeypatch, False)
    add_project_document(main_window, tmp_path)

    main_window.rebuild_annotation()

    assert loaded == [("a.TextGrid", False)]
    assert asked == []


def test_rebuild_annotation_reports_a_file_without_a_textgrid(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav")
    loaded, asked = stub_overwrite_scenario(monkeypatch, True)
    messages = capture_information(monkeypatch)
    add_project_document(main_window, tmp_path)

    main_window.rebuild_annotation()

    assert loaded == [] and asked == []
    assert messages == ["There is no TextGrid for a in the project directory."]


def test_rebuild_annotation_does_nothing_without_a_current_document(
    main_window: MainWindow, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))

    main_window.rebuild_annotation()  # does not raise


def test_open_single_document_accepts_textgrid_with_any_case_suffix(
    main_window: MainWindow, tmp_path: Path, opened: list
):
    wav, textgrid = str(tmp_path / "a.wav"), str(tmp_path / "a.textgrid")

    main_window.open_single_document([wav, textgrid], str(tmp_path))

    assert opened == [([("a", wav, textgrid)], str(tmp_path))]


@pytest.mark.parametrize("name", ["a.eaf", "a.srt", "a.EAF", "a.SRT"])
def test_open_single_document_accepts_elan_and_subtitle_files(
    main_window: MainWindow, tmp_path: Path, opened: list, name: str
):
    wav, annotation = str(tmp_path / "a.wav"), str(tmp_path / name)

    main_window.open_single_document([wav, annotation], str(tmp_path))

    assert opened == [([("a", wav, annotation)], str(tmp_path))]


def test_a_sound_file_on_its_own_is_offered_the_annotation_next_to_it(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    wav, srt = str(tmp_path / "a.wav"), str(tmp_path / "a.srt")
    (tmp_path / "a.srt").write_text("")
    offered = []

    def ask(parent: object, audio_file: str, annotation_files: list[str]) -> str:
        offered.append((audio_file, annotation_files))
        return annotation_files[0]

    monkeypatch.setattr(main_window_module, "ask_open_with_annotation", ask)

    main_window.open_single_document([wav])

    assert offered == [(wav, [srt])]
    assert opened == [([(str(tmp_path / "a"), wav, srt)], None)]


def test_a_sound_file_is_opened_alone_when_the_annotation_offered_is_declined(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    wav = str(tmp_path / "a.wav")
    (tmp_path / "a.eaf").write_text("")
    monkeypatch.setattr(
        main_window_module, "ask_open_with_annotation", lambda *args: None
    )

    main_window.open_single_document([wav])

    assert opened == [([(str(tmp_path / "a"), wav, None)], None)]


def test_no_annotation_is_offered_when_one_is_chosen_or_the_file_is_in_the_project(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    (tmp_path / "a.srt").write_text("")
    (tmp_path / "b.srt").write_text("")
    asked = []
    monkeypatch.setattr(
        main_window_module,
        "ask_open_with_annotation",
        lambda *args: asked.append(args),
    )

    main_window.open_single_document(
        [str(tmp_path / "a.wav"), str(tmp_path / "a.TextGrid")]
    )
    main_window.open_single_document([str(tmp_path / "b.wav")], str(tmp_path))

    assert asked == []


# --------------------------- spectrogram only for the shown tab ---------------------------


def test_only_the_current_tab_is_shown(main_window: MainWindow):
    first = add_document(main_window, "one.wav")
    second = add_document(main_window, "two.wav")
    third = add_document(main_window, "three.wav")

    assert [d.view_model.is_shown for d in (first, second, third)] == [
        False,
        False,
        True,
    ]


def test_switching_tabs_changes_which_document_is_shown(main_window: MainWindow):
    first = add_document(main_window, "one.wav")
    second = add_document(main_window, "two.wav")

    main_window.tab_widget.setCurrentIndex(0)

    assert first.view_model.is_shown
    assert not second.view_model.is_shown


def test_closing_the_current_tab_shows_the_one_that_becomes_current(
    main_window: MainWindow,
):
    first = add_document(main_window, "one.wav")
    add_document(main_window, "two.wav")
    assert not first.view_model.is_shown

    main_window.close_current_tab()

    assert main_window.tab_widget.count() == 1
    assert first.view_model.is_shown


def test_clip_tab_opens_hidden_behind_its_source(main_window: MainWindow):
    source = add_document(main_window, "source.wav")
    load_signal(source, np.arange(10000), fs=1000)
    source.view_model.start_selection(2.0)
    source.view_model.continue_selection(3.0)

    main_window.copy_selection()

    assert main_window.tab_widget.count() == 2
    clip = main_window.tab_widget.widget(1)
    assert isinstance(clip, DocumentView)
    assert not clip.view_model.is_shown
    assert source.view_model.is_shown


# --------------------------- annotation menu ---------------------------


def test_annotation_menu_offers_tier_rebuild_and_export_actions(
    main_window: MainWindow,
):
    menu = next(
        action.menu()
        for action in main_window.menuBar().actions()
        if action.text().replace("&", "") == "Annotation"
    )

    assert [a for a in menu.actions() if not a.isSeparator()] == [
        main_window.add_tiers_action,
        main_window.arrange_tiers_action,
        main_window.choose_fonts_action,
        main_window.rebuild_annotation_action,
        main_window.export_annotation_action,
    ]


def test_add_tiers_is_disabled_until_a_document_is_open(main_window: MainWindow):
    assert not main_window.add_tiers_action.isEnabled()

    add_document(main_window)

    assert main_window.add_tiers_action.isEnabled()


def test_add_tiers_is_disabled_again_when_the_last_document_closes(
    main_window: MainWindow,
):
    add_document(main_window)

    main_window.close_current_tab()

    assert not main_window.add_tiers_action.isEnabled()


def test_add_tiers_asks_the_current_document_which_tiers_to_add(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    opened: list[DocumentView] = []
    monkeypatch.setattr(
        DocumentView, "open_add_tiers", lambda self: opened.append(self)
    )
    add_document(main_window, "one.wav")
    second = add_document(main_window, "two.wav")
    load_signal(second, np.zeros(2000), fs=1000)

    main_window.add_tiers_action.trigger()

    assert opened == [second]


def test_add_tiers_shows_the_annotation_plot_if_it_is_hidden(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(DocumentView, "open_add_tiers", lambda self: None)
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    assert not doc.view_model.plot_layout_state.has_annotation()

    main_window.add_tiers()

    assert doc.view_model.plot_layout_state.has_annotation()
    assert PlotType.ANNOTATION in main_window.view_model.display_plan


def test_add_tiers_leaves_the_annotation_plot_alone_if_it_is_shown(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(DocumentView, "open_add_tiers", lambda self: None)
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    main_window.plot_annotations()
    assert doc.view_model.plot_layout_state.has_annotation()

    main_window.add_tiers()

    assert doc.view_model.plot_layout_state.has_annotation()


def test_add_tiers_does_nothing_without_a_document(main_window: MainWindow):
    main_window.add_tiers()  # must not raise


# --------------------------- show and order tiers ---------------------------


def stub_tier_dialog(
    monkeypatch: pytest.MonkeyPatch, chosen: list[TierDisplayState] | None
) -> list[list[TierDisplayState]]:
    offered: list[list[TierDisplayState]] = []

    def get_tiers(
        tiers: list[TierDisplayState], parent: QWidget | None = None
    ) -> list[TierDisplayState] | None:
        offered.append(tiers)
        return chosen

    monkeypatch.setattr(TierDisplayDialog, "get_tiers", get_tiers)
    return offered


def test_arrange_tiers_is_disabled_until_a_document_is_open(main_window: MainWindow):
    assert not main_window.arrange_tiers_action.isEnabled()

    add_document(main_window)

    assert main_window.arrange_tiers_action.isEnabled()


def test_arrange_tiers_is_disabled_again_when_the_last_document_closes(
    main_window: MainWindow,
):
    add_document(main_window)

    main_window.close_current_tab()

    assert not main_window.arrange_tiers_action.isEnabled()


def test_arrange_tiers_does_nothing_without_a_document(main_window: MainWindow):
    main_window.arrange_tiers()  # must not raise


def test_arrange_tiers_offers_the_current_documents_tier_display(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    tiers = [TierDisplayState("word", 1), TierDisplayState("phone")]
    offered = stub_tier_dialog(monkeypatch, None)
    doc = add_document(main_window)
    monkeypatch.setattr(doc.view_model, "tier_display", lambda: tiers)

    main_window.arrange_tiers_action.trigger()

    assert offered == [tiers]


def test_arrange_tiers_applies_the_choice_to_every_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_tier_dialog(
        monkeypatch,
        [
            TierDisplayState("word", 2),
            TierDisplayState("phone"),
            TierDisplayState("tone", 1),
        ],
    )
    first = add_document(main_window, "one.wav")
    second = add_document(main_window, "two.wav")
    load_signal(second, np.zeros(2000), fs=1000)

    main_window.arrange_tiers()

    assert main_window.view_model.hidden_tiers == ["phone"]
    assert main_window.view_model.tier_order == ["tone", "word"]
    for doc in (first, second):
        annotation_vm = doc.view_model.annotation_view_model
        assert annotation_vm.hidden_tiers == ["phone"]
        assert annotation_vm.tier_order == ["tone", "word"]


def test_arrange_tiers_cancelled_changes_nothing(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_tier_dialog(monkeypatch, None)
    doc = add_document(main_window)
    main_window.set_tier_display(["word"], ["phone"])

    main_window.arrange_tiers()

    assert main_window.view_model.hidden_tiers == ["word"]
    assert main_window.view_model.tier_order == ["phone"]
    assert doc.view_model.annotation_view_model.hidden_tiers == ["word"]


def test_arrange_tiers_shows_the_annotation_plot_if_it_is_hidden(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_tier_dialog(monkeypatch, [TierDisplayState("word", 1)])
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    assert not doc.view_model.plot_layout_state.has_annotation()

    main_window.arrange_tiers()

    assert doc.view_model.plot_layout_state.has_annotation()
    assert PlotType.ANNOTATION in main_window.view_model.display_plan


def test_arrange_tiers_leaves_the_annotation_plot_alone_if_it_is_shown(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_tier_dialog(monkeypatch, [TierDisplayState("word", 1)])
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    main_window.plot_annotations()
    assert doc.view_model.plot_layout_state.has_annotation()

    main_window.arrange_tiers()

    assert doc.view_model.plot_layout_state.has_annotation()


def test_arrange_tiers_cancelled_does_not_show_the_annotation_plot(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_tier_dialog(monkeypatch, None)
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)

    main_window.arrange_tiers()

    assert not doc.view_model.plot_layout_state.has_annotation()


def test_a_new_document_shows_the_tiers_the_same_way(main_window: MainWindow):
    main_window.view_model.set_tier_display(["phone"], ["word"])
    doc = add_document(main_window)

    main_window.apply_tier_display(doc.view_model)

    annotation_vm = doc.view_model.annotation_view_model
    assert annotation_vm.hidden_tiers == ["phone"]
    assert annotation_vm.tier_order == ["word"]


def add_tier_when_adding_tiers(
    doc: DocumentView, monkeypatch: pytest.MonkeyPatch, added: str
):
    names = ["word"]
    monkeypatch.setattr(doc.view_model, "tier_names", lambda: list(names))
    monkeypatch.setattr(
        DocumentView, "open_add_tiers", lambda self: names.append(added)
    )


def test_add_tiers_shows_a_tier_just_added_that_was_hidden(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    main_window.set_tier_display(["tone", "phone"], ["word"])
    add_tier_when_adding_tiers(doc, monkeypatch, "tone")

    main_window.add_tiers()

    assert main_window.view_model.hidden_tiers == ["phone"]
    assert main_window.view_model.tier_order == ["word"]
    assert doc.view_model.annotation_view_model.hidden_tiers == ["phone"]


def test_add_tiers_leaves_hidden_tiers_alone_when_none_was_added_back(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    main_window.set_tier_display(["phone"], [])
    add_tier_when_adding_tiers(doc, monkeypatch, "tone")

    main_window.add_tiers()

    assert main_window.view_model.hidden_tiers == ["phone"]


# --------------------------- Ctrl+L with several documents open ---------------------------


def open_two_documents_with_annotation(
    main_window: MainWindow, qtbot: QtBot
) -> tuple[DocumentView, DocumentView]:
    docs = []
    for name in ("one.wav", "two.wav"):
        doc = add_document(main_window, name)
        load_signal(doc, np.zeros(2000), fs=1000)
        doc.view_model.toggle_annotations()
        QApplication.processEvents()
        docs.append(doc)
    main_window.show()
    qtbot.waitExposed(main_window)
    main_window.activateWindow()
    QApplication.processEvents()
    return docs[0], docs[1]


def test_ctrl_l_is_not_ambiguous_with_two_documents_open(
    main_window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
):
    from PyQt6.QtCore import qInstallMessageHandler
    from PyQt6.QtTest import QTest

    open_two_documents_with_annotation(main_window, qtbot)
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        QTest.keyClick(main_window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)

    assert [m for m in messages if "mbiguous" in m] == []


def test_ctrl_l_reaches_the_annotation_of_the_document_on_screen_only(
    main_window: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
):
    from PyQt6.QtTest import QTest

    first, second = open_two_documents_with_annotation(main_window, qtbot)
    reached: list[DocumentView] = []
    for doc in (first, second):
        plot = next(p for p in doc.document_plots if isinstance(p, AnnotationPlot))
        plot.create_label_action.triggered.connect(lambda *_, d=doc: reached.append(d))

    QTest.keyClick(main_window, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert reached == [second]  # the second tab is the one on screen


# --------------------------- choose fonts ---------------------------


def stub_font_dialog(
    monkeypatch: pytest.MonkeyPatch, chosen: dict[str, str] | None
) -> list[tuple[list[str], dict[str, str]]]:
    offered: list[tuple[list[str], dict[str, str]]] = []

    def get_fonts(
        names: list[str], fonts: dict[str, str], parent: QWidget | None = None
    ) -> dict[str, str] | None:
        offered.append((names, fonts))
        return chosen

    monkeypatch.setattr(TierFontDialog, "get_fonts", get_fonts)
    return offered


def test_choose_fonts_is_enabled_only_while_a_document_is_open(
    main_window: MainWindow,
):
    assert not main_window.choose_fonts_action.isEnabled()

    add_document(main_window)

    assert main_window.choose_fonts_action.isEnabled()


def test_choose_fonts_does_nothing_without_a_document(main_window: MainWindow):
    main_window.choose_fonts()  # must not raise


def test_choose_fonts_offers_the_tiers_as_plotted_and_the_current_fonts(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    offered = stub_font_dialog(monkeypatch, None)
    doc = add_document(main_window)
    tiers = [
        TierDisplayState("phone", 1),
        TierDisplayState("word", 2),
        TierDisplayState("tone"),
    ]
    monkeypatch.setattr(doc.view_model, "tier_display", lambda: tiers)
    main_window.view_model.set_tier_fonts({"word": "Charis SIL"})

    main_window.choose_fonts_action.trigger()

    assert offered == [(["word", "phone", "tone"], {"word": "Charis SIL"})]


def test_choose_fonts_applies_the_choice_to_every_document(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_font_dialog(monkeypatch, {"word": "Charis SIL"})
    first = add_document(main_window, "one.wav")
    second = add_document(main_window, "two.wav")
    load_signal(second, np.zeros(2000), fs=1000)

    main_window.choose_fonts()

    assert main_window.view_model.tier_fonts == {"word": "Charis SIL"}
    for doc in (first, second):
        assert doc.view_model.annotation_view_model.tier_fonts == {"word": "Charis SIL"}


def test_choose_fonts_cancelled_changes_nothing(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_font_dialog(monkeypatch, None)
    doc = add_document(main_window)
    main_window.view_model.set_tier_fonts({"word": "Charis SIL"})

    main_window.choose_fonts()

    assert main_window.view_model.tier_fonts == {"word": "Charis SIL"}
    assert doc.view_model.annotation_view_model.tier_fonts == {}


def test_choose_fonts_shows_the_annotation_plot_if_it_is_hidden(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    stub_font_dialog(monkeypatch, {"word": "Charis SIL"})
    doc = add_document(main_window)
    load_signal(doc, np.zeros(2000), fs=1000)
    assert not doc.view_model.plot_layout_state.has_annotation()

    main_window.choose_fonts()

    assert doc.view_model.plot_layout_state.has_annotation()


def test_a_document_is_given_the_chosen_fonts_when_it_opens(main_window: MainWindow):
    main_window.view_model.set_tier_fonts({"word": "Charis SIL"})
    doc_view_model = main_window.view_model_factory.create(DocumentViewModel)

    main_window.apply_tier_display(doc_view_model)

    assert doc_view_model.annotation_view_model.tier_fonts == {"word": "Charis SIL"}


# --------------------------- tier search ---------------------------


def add_stemmed_document(main_window: MainWindow, file_stem: str) -> DocumentView:
    vm = main_window.view_model_factory.create(DocumentViewModel, file_stem, None)
    doc = DocumentView(vm)
    main_window.tab_widget.addTab(doc, file_stem)
    main_window.tab_widget.setCurrentIndex(main_window.tab_widget.count() - 1)
    return doc


def test_tier_search_action_opens_dialog_for_tier(main_window: MainWindow):
    doc = add_stemmed_document(main_window, "a")

    doc.view_model.state_changed.emit(TierSearchAction("word", "a", 1.5))
    # The document does not know about the main window until opened through it
    main_window.on_doc_state_change(TierSearchAction("word", "a", 1.5))

    dialog = main_window.tier_search_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog.view_model.tier_name == "word"
    assert dialog.view_model.file_stem == "a"
    assert dialog.view_model.cursor[:2] == ("a", 1.5)


def test_the_context_menu_can_ask_for_the_tiers_to_be_shown_and_ordered(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    add_stemmed_document(main_window, "a")
    asked: list = []
    monkeypatch.setattr(
        TierDisplayDialog,
        "get_tiers",
        staticmethod(lambda tiers, parent=None: asked.append(tiers)),
    )

    main_window.on_doc_state_change(ArrangeTiersAction())

    assert len(asked) == 1


def test_tier_search_reuses_dialog_and_retargets_it(main_window: MainWindow):
    main_window.on_doc_state_change(TierSearchAction("word", "a"))
    dialog = main_window.tier_search_dialog

    main_window.on_doc_state_change(TierSearchAction("phone", "b"))

    assert main_window.tier_search_dialog is dialog
    assert dialog is not None
    assert dialog.view_model.tier_name == "phone"
    assert dialog.view_model.file_stem == "b"


def test_tier_search_dialog_is_replaced_when_project_changes(main_window: MainWindow):
    main_window.on_doc_state_change(TierSearchAction("word", "a"))
    first = main_window.tier_search_dialog

    main_window.view_model.set_dir_path("/project")
    main_window.on_doc_state_change(TierSearchAction("word", "a"))

    assert main_window.tier_search_dialog is not first
    assert isinstance(main_window.tier_search_dialog, TierSearchDialog)
    assert main_window.tier_search_dialog.view_model.is_project
    assert first is not None
    assert not first.isVisible()


def test_match_in_open_document_switches_to_it_and_reveals_span(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    first = add_stemmed_document(main_window, "a")
    add_stemmed_document(main_window, "b")
    revealed = []
    monkeypatch.setattr(first.view_model, "reveal_span", lambda *a: revealed.append(a))

    main_window.show_tier_match(TierSearchMatchState("a", 1.0, 2.0))

    assert main_window.get_current_document() is first
    assert revealed == [(1.0, 2.0)]


def test_match_in_unopened_file_opens_it_first(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.wav").write_bytes(b"")
    main_window.view_model.set_dir_path(str(tmp_path))
    opened = []
    revealed = []

    def fake_open_files(files: list, dir_path: str | None):
        opened.append((files, dir_path))
        doc = add_stemmed_document(main_window, files[0][0])
        monkeypatch.setattr(
            doc.view_model, "reveal_span", lambda *a: revealed.append(a)
        )

    monkeypatch.setattr(main_window, "open_files", fake_open_files)

    main_window.show_tier_match(TierSearchMatchState("sub/c", 3.0, 4.0))

    assert opened == [
        ([OpenableFile("sub/c", str(tmp_path / "sub" / "c.wav"), None)], str(tmp_path))
    ]
    assert revealed == [(3.0, 4.0)]


def test_match_in_file_that_cannot_be_opened_shows_message(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: messages.append(args[2])
    )

    main_window.show_tier_match(TierSearchMatchState("gone", 0.0, 1.0))

    assert len(messages) == 1
    assert main_window.tab_widget.count() == 0


def test_match_in_closed_document_without_project_shows_message(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: messages.append(args[2])
    )

    main_window.show_tier_match(TierSearchMatchState("/tmp/closed", 0.0, 1.0))

    assert len(messages) == 1


def test_changed_labels_reload_only_documents_showing_those_files(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch
):
    changed = add_stemmed_document(main_window, "a")
    untouched = add_stemmed_document(main_window, "b")
    reloaded = []
    monkeypatch.setattr(
        changed.view_model, "reload_annotation", lambda: reloaded.append("a")
    )
    monkeypatch.setattr(
        untouched.view_model, "reload_annotation", lambda: reloaded.append("b")
    )

    main_window.on_tier_search_state_change(TierLabelsChangedState(frozenset({"a"})))

    assert reloaded == ["a"]


# --------------------------- layout, extra information and the database window ---------------------------


def test_new_project_asks_how_it_is_organized_before_building_the_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    accept_layout_dialog: list[ProjectLayoutDialog],
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav")  # b has no TextGrid
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)

    main_window.select_path_to_open()

    assert len(accept_layout_dialog) == 1
    assert "[import]" in (tmp_path / "phonlab.toml").read_text()
    assert "project_import" in main_window.view_model.job_managers


def test_new_project_that_needs_no_decisions_is_not_asked(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    accept_layout_dialog: list[ProjectLayoutDialog],
):
    make_project(tmp_path, "a.wav", "a.TextGrid")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)

    main_window.select_path_to_open()

    assert accept_layout_dialog == []
    assert "[import]" in (tmp_path / "phonlab.toml").read_text()  # saved all the same


def test_cancelling_the_layout_dialog_opens_no_project(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
):
    make_project(tmp_path, "a.wav", "a.TextGrid", "b.wav")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    monkeypatch.setattr(
        ProjectLayoutDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )

    main_window.select_path_to_open()

    assert opened == []
    assert "project_import" not in main_window.view_model.job_managers
    assert main_window.view_model.dir_path is None


def test_project_with_a_database_is_opened_without_asking_about_its_layout(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    accept_layout_dialog: list[ProjectLayoutDialog],
):
    make_project(tmp_path, "a.wav", "b.wav", database=True)
    patch_directory_dialog(monkeypatch, str(tmp_path))

    main_window.select_path_to_open()

    assert accept_layout_dialog == []
    assert len(opened) == 1


def test_new_project_records_the_talkers_the_layout_finds(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    opened: list,
    project_repository: SeedableAnnotationRepository,
):
    make_project(tmp_path)
    for talker, stem in (("t1", "a"), ("t2", "b")):
        (tmp_path / talker).mkdir()
        (tmp_path / talker / f"{stem}.wav").write_bytes(b"")
        write_simple_textgrid(tmp_path / talker / f"{stem}.TextGrid")
    patch_directory_dialog(monkeypatch, str(tmp_path))
    capture_information(monkeypatch)

    main_window.select_path_to_open()
    run_import_job(main_window)

    assert {r.file_stem: r.talkers for r in project_repository.list_recordings()} == {
        "t1/a": ["t1"],
        "t2/b": ["t2"],
    }


def test_project_menu_items_about_layout_and_data_need_a_project(
    main_window: MainWindow, tmp_path: Path
):
    actions = (
        main_window.project_layout_action,
        main_window.inspect_database_action,
    )
    assert [action.isEnabled() for action in actions] == [False] * 2

    main_window.view_model.set_dir_path(str(tmp_path))
    main_window.update_project_actions()

    assert [action.isEnabled() for action in actions] == [True] * 2


def test_reviewing_the_layout_updates_the_project_database(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    accept_layout_dialog: list[ProjectLayoutDialog],
):
    make_project(tmp_path, "a.wav", "a.TextGrid", database=True)
    main_window.view_model.set_dir_path(str(tmp_path))
    messages = capture_information(monkeypatch)

    main_window.edit_project_layout()

    assert len(accept_layout_dialog) == 1  # asked although nothing needed deciding
    run_import_job(main_window)
    assert messages == ["The project layout has been applied."]


def test_cancelling_the_layout_review_changes_nothing(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a.wav", database=True)
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        ProjectLayoutDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )

    main_window.edit_project_layout()

    assert "project_import" not in main_window.view_model.job_managers
    assert "[import]" not in (tmp_path / "phonlab.toml").read_text()


def test_adding_talkers_reports_a_file_that_cannot_be_used(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    (tmp_path / "info.csv").write_text("only,a,header\n")
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "info.csv"), "")),
    )
    errors: list = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args: errors.append(args))
    )

    main_window.add_talkers()

    assert len(errors) == 1


def test_adding_talkers_shows_the_dialog_for_the_chosen_file(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    (tmp_path / "info.csv").write_text("talker,age\nAnn,31\n")
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "info.csv"), "")),
    )
    shown: list[MetadataImportDialog] = []
    monkeypatch.setattr(
        MetadataImportDialog,
        "exec",
        lambda self: shown.append(self) or QDialog.DialogCode.Rejected,
    )

    main_window.add_talkers()

    [dialog] = shown
    assert dialog.state.file_name == "info.csv"


def test_adding_talkers_does_nothing_when_no_file_is_chosen(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: ("", "")),
    )

    main_window.add_talkers()  # would raise if it went on


def test_inspecting_the_database_opens_a_window_that_closes_with_the_project(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    database = SQLiteDatabase()  # tables are only read from a real project database
    database.connect(str(tmp_path))
    view_model = make_database_view_model(
        str(tmp_path), DataAnnotationRepository(AnnotationDataSource(database))
    )
    monkeypatch.setattr(
        main_window.view_model_factory, "create", lambda *args, **kwargs: view_model
    )

    main_window.inspect_database()

    dialog = main_window.database_dialog
    assert dialog is not None
    assert dialog.table_combo.currentText() == "recording"

    main_window.close_project()

    assert main_window.database_dialog is None
    database.engine.dispose()


def test_the_project_can_be_closed_after_the_database_window_was_closed(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    database = SQLiteDatabase()
    database.connect(str(tmp_path))
    view_model = make_database_view_model(
        str(tmp_path), DataAnnotationRepository(AnnotationDataSource(database))
    )
    monkeypatch.setattr(
        main_window.view_model_factory, "create", lambda *args, **kwargs: view_model
    )
    main_window.inspect_database()
    dialog = main_window.database_dialog
    assert dialog is not None

    dialog.close()  # the window deletes itself
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert main_window.database_dialog is None
    main_window.close_project()  # used to raise: the window was already deleted
    database.engine.dispose()


def test_open_files_opens_channel_files_as_one_document_without_asking(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    left, right = tmp_path / "a_L.wav", tmp_path / "a_R.wav"
    left.write_bytes(b"")
    right.write_bytes(b"")
    monkeypatch.setattr(
        OpenAudioDialog,
        "get_options",
        staticmethod(lambda *args, **kwargs: pytest.fail("asked about the audio")),
    )
    loaded: list = []
    monkeypatch.setattr(
        DocumentView,
        "load_audio",
        lambda self, files, options: loaded.append((files, options)),
    )

    main_window.open_files(
        [OpenableFile("a", str(left), None, (str(left), str(right)))], str(tmp_path)
    )

    [(files, options)] = loaded
    assert files == [str(left), str(right)]
    assert options.channel_mode == "stereo"
    assert options.retained_channels == [0, 1]
    assert main_window.tab_widget.tabText(0) == "a"


def test_a_tier_match_in_a_channel_recording_opens_its_channel_files(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    make_project(tmp_path, "a_L.wav", "a_R.wav", database=True)
    SaveProjectLayout()(
        str(tmp_path),
        ProjectLayout(channels=(ChannelRole("L", "_L"), ChannelRole("R", "_R"))),
    )
    main_window.view_model.set_dir_path(str(tmp_path))
    opened: list = []
    monkeypatch.setattr(
        main_window, "open_files", lambda files, dir_path: opened.append(files)
    )

    main_window.open_project_document("a")

    [[file]] = opened
    assert file.file_stem == "a"
    assert file.channel_files == (str(tmp_path / "a_L.wav"), str(tmp_path / "a_R.wav"))


def test_adding_talkers_reads_a_table_without_asking_what_its_rows_are_about(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    table = tmp_path / "talkers.csv"
    table.write_text("talker,age\nt1,31\n")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(table), "")),
    )
    shown: list[MetadataImportDialog] = []
    monkeypatch.setattr(
        MetadataImportDialog,
        "exec",
        lambda self: shown.append(self) or QDialog.DialogCode.Rejected,
    )

    main_window.add_talkers()

    [dialog] = shown
    assert dialog.about_group.isHidden()
    assert dialog.state.target == "talker"


def test_adding_words_reads_a_table_of_words_and_reports_what_it_made(
    main_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project_repository: SeedableAnnotationRepository,
):
    main_window.view_model.set_dir_path(str(tmp_path))
    id = project_repository.create_annotation("a")
    project_repository.create_types(
        id, [AnnotationType("word", [AnnotationLabel(0, 0, "the", id=0)])]
    )
    table = tmp_path / "words.csv"
    table.write_text("word,freq\nthe,5\ncat,2\n")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(table), "")),
    )
    messages = capture_information(monkeypatch)
    monkeypatch.setattr(
        main_window.view_model_factory,
        "create",
        lambda *args, **kwargs: make_word_import_view_model(
            str(tmp_path), str(table), project_repository
        ),
    )
    monkeypatch.setattr(
        WordImportDialog,
        "exec",
        lambda self: self.accept_import() or QDialog.DialogCode.Accepted,
    )

    main_window.add_words()

    assert project_repository.words["the"] == {"freq": 5}
    assert "2 words and 1 columns" in messages[0]


def test_adding_words_to_a_project_without_tiers_says_so(
    main_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    main_window.view_model.set_dir_path(str(tmp_path))
    table = tmp_path / "words.csv"
    table.write_text("word,freq\nthe,5\n")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(table), "")),
    )
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda parent, title, text, *a: errors.append(text)),
    )

    main_window.add_words()

    assert "The project database has no annotation." in errors[0]
