from collections.abc import Callable, Sequence
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QWidget,
)

from core.project.scan_project_files import (
    is_annotation_file,
    is_audio_file,
    matching_annotation_files,
)
from core.settings.app_settings import settings
from phonlab_project.metadata import MetadataTarget
from res.constants import PROJECT_MARKER_FILES
from ui.annotation.component.tier_display_dialog import TierDisplayDialog
from ui.annotation.component.tier_font_dialog import TierFontDialog
from ui.annotation.component.tier_search_dialog import TierSearchDialog
from ui.annotation.state.arrange_tiers_state import ArrangeTiersAction
from ui.annotation.state.tier_display_state import (
    hidden_and_order_from,
    listed_as_plotted,
)
from ui.annotation.state.tier_search_state import (
    TierLabelsChangedState,
    TierSearchAction,
    TierSearchMatchState,
)
from ui.annotation.tier_search_view_model import TierSearchViewModel
from ui.base.dependency_factory import ViewModelFactory
from ui.base.state import State
from ui.database_view.database_dialog import DatabaseDialog
from ui.database_view.database_view_model import DatabaseViewModel
from ui.document.component.overwrite_annotation_dialog import ask_overwrite_annotation
from ui.document.document_view import DocumentView
from ui.document.document_view_model import DocumentViewModel
from ui.document.state.audio_channel_state import AudioState
from ui.main.component.add_to_project_dialog import (
    NEW_ANNOTATIONS,
    REPLACEMENT_ANNOTATIONS,
    TALKERS,
    WORDS,
    AddToProjectDialog,
)
from ui.main.component.open_audio_dialog import DEFAULT_SAMPLE_RATE, OpenAudioDialog
from ui.main.component.open_path_dialog import OpenPathDialog
from ui.main.component.open_with_annotation_dialog import ask_open_with_annotation
from ui.main.component.save_audio_dialog import SaveAudioDialog
from ui.main.main_view_model import MainViewModel
from ui.main.state.audio_open_options import AudioOpenOptionsState, ChannelMode
from ui.main.state.openable_file import OpenableFile
from ui.main.state.project_import_state import ImportStageState, ProjectImportState
from ui.metadata_import.metadata_import_dialog import MetadataImportDialog
from ui.metadata_import.metadata_import_view_model import MetadataImportViewModel
from ui.project_layout.project_layout_dialog import ProjectLayoutDialog
from ui.project_layout.project_layout_view_model import ProjectLayoutViewModel
from ui.spectrogram.state.audio_prepped import AudioPrepped
from ui.word_import.word_import_dialog import WordImportDialog
from ui.word_import.word_import_view_model import WordImportViewModel


class MainWindow(QMainWindow):
    def __init__(
        self, view_model_factory: ViewModelFactory, parent: QWidget | None = None
    ):
        super().__init__(parent)

        self.setWindowTitle("Phonlab")
        self.resize(1200, 800)

        self.filters = (
            "Sound files and annotations (*.wav *.WAV *.TextGrid *.textgrid "
            f"*.TEXTGRID *.eaf *.srt *.cha {' '.join(PROJECT_MARKER_FILES)})"
        )
        self.splash = None
        self.progress_dialog: QProgressDialog | None = None
        self.database_dialog: DatabaseDialog | None = None
        self.on_import_finished: Callable[[ProjectImportState], None] | None = None
        self.import_title = ""
        self.clipboard: AudioState | None = None
        self.clip_counters: dict[str, int] = {}
        self.tier_search_dialog: TierSearchDialog | None = None
        self.tier_search_dir_path: str | None = None

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tab_widget)

        self.view_model_factory = view_model_factory
        self.view_model = view_model_factory.create(MainViewModel)
        self.view_model.subscribe(self.on_view_model_state_changed)

        # --------- Menu --------------------
        self.create_menus()

        # ------- toolbar -------------
        self.create_toolbar()

    def create_menus(self):
        """Create application menus"""
        mainMenu = self.menuBar()
        self.style()

        self.open_action = QAction(
            QIcon.fromTheme("document-open"), self.tr("&Open"), self
        )
        self.open_action.setStatusTip(
            self.tr("Open a sound file, or a directory as a project")
        )
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.select_path_to_open)

        self.close_action = QAction(
            QIcon.fromTheme("window-close"), self.tr("&Close"), self
        )
        self.close_action.setStatusTip(self.tr("Close current file"))
        self.close_action.setShortcut("Ctrl+W")
        self.close_action.triggered.connect(self.close_current_tab)

        self.save_audio_action = QAction(self.tr("Save &Audio…"), self)
        self.save_audio_action.setStatusTip(
            self.tr("Save the current document's audio to a file")
        )
        self.save_audio_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_audio_action.triggered.connect(self.save_audio)

        self.export_annotation_action = QAction(self.tr("&Export Annotation…"), self)
        self.export_annotation_action.setStatusTip(
            self.tr("Export the current document's annotations to a file")
        )
        self.export_annotation_action.triggered.connect(self.save_textgrid)

        self.save_layout_action = QAction(self.tr("Save Window &Layout"), self)
        self.save_layout_action.setStatusTip(
            self.tr("Save which plots are shown in this project")
        )
        self.save_layout_action.setEnabled(False)
        self.save_layout_action.triggered.connect(self.save_window_layout)

        self.project_layout_action = QAction(self.tr("Project &Layout…"), self)
        self.project_layout_action.setStatusTip(
            self.tr("Review how the project's folders and files are organized")
        )
        self.project_layout_action.triggered.connect(self.edit_project_layout)

        self.inspect_database_action = QAction(
            self.tr("Inspect Project &Database…"), self
        )
        self.inspect_database_action.setStatusTip(
            self.tr("Look at the tables in the project database")
        )
        self.inspect_database_action.triggered.connect(self.inspect_database)

        self.audio_info_action = QAction(self.tr("Audio &Info"), self)
        self.audio_info_action.setShortcut("Ctrl+I")
        self.audio_info_action.setStatusTip(
            self.tr("Show sample rate, duration, and amplitude of the current document")
        )
        self.audio_info_action.triggered.connect(self.show_audio_info)

        self.exit_action = QAction(
            QIcon.fromTheme("application-exit"), self.tr("&Quit"), self
        )
        self.exit_action.setStatusTip(self.tr("Terminate the program"))
        self.exit_action.triggered.connect(self.quit_app)

        # File Menu
        if mainMenu is not None:
            fileMenu = mainMenu.addMenu("&File")
        if fileMenu is not None:
            fileMenu.addAction(self.open_action)
            fileMenu.addAction(self.close_action)
            fileMenu.addSeparator()
            fileMenu.addAction(self.save_audio_action)
            fileMenu.addSeparator()
            fileMenu.addAction(self.audio_info_action)
            fileMenu.addSeparator()
            fileMenu.addAction(self.exit_action)

        self.undo_action = QAction(self.tr("&Undo"), self)
        self.undo_action.setStatusTip(self.tr("Undo the last cut or paste"))
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)

        self.redo_action = QAction(self.tr("&Redo"), self)
        self.redo_action.setStatusTip(self.tr("Redo the last undone cut or paste"))
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)

        self.cut_action = QAction(self.tr("Cu&t"), self)
        self.cut_action.setStatusTip(self.tr("Cut the selected audio"))
        self.cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        self.cut_action.triggered.connect(self.cut_selection)

        self.copy_action = QAction(self.tr("&Copy"), self)
        self.copy_action.setStatusTip(self.tr("Copy the selected audio"))
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self.copy_selection)

        self.paste_action = QAction(self.tr("&Paste"), self)
        self.paste_action.setStatusTip(self.tr("Paste audio at the mark"))
        self.paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self.paste_action.triggered.connect(self.paste_at_cursor)

        self.paste_special_action = QAction(self.tr("Paste &Special..."), self)
        self.paste_special_action.setStatusTip(
            self.tr(
                "Paste the clipboard clip, optionally reversed or into a new stereo channel"
            )
        )
        self.paste_special_action.setShortcut("Ctrl+Shift+V")
        self.paste_special_action.triggered.connect(self.paste_special)

        # Edit Menu
        if mainMenu is not None:
            editMenu = mainMenu.addMenu("&Edit")
        if editMenu is not None:
            editMenu.addAction(self.undo_action)
            editMenu.addAction(self.redo_action)
            editMenu.addSeparator()
            editMenu.addAction(self.cut_action)
            editMenu.addAction(self.copy_action)
            editMenu.addAction(self.paste_action)
            editMenu.addAction(self.paste_special_action)

        self.waveview_action = QAction(
            QIcon.fromTheme("audio-x-generic"), self.tr("&Wave"), self
        )
        self.waveview_action.setStatusTip(self.tr("View audio waveform"))
        self.waveview_action.setShortcut("Ctrl+1")
        self.waveview_action.triggered.connect(self.plot_wave)

        self.sgramview_action = QAction(
            QIcon.fromTheme("view-media-visualization"), self.tr("&Spectrogram"), self
        )
        self.sgramview_action.setStatusTip(self.tr("View spectrogram"))
        self.sgramview_action.setShortcut("Ctrl+2")
        self.sgramview_action.triggered.connect(self.plot_wave_sgram)
        self.sgramview_action.setEnabled(False)

        if settings.enable_annotation:
            self.annotationview_action = QAction(
                QIcon.fromTheme("view-media-visualization"),
                self.tr("&Annotation"),
                self,
            )
            self.annotationview_action.setStatusTip(self.tr("View annotations"))
            self.annotationview_action.setShortcut("Ctrl+3")
            self.annotationview_action.triggered.connect(self.plot_annotations)

        self.viewall_action = QAction(
            QIcon.fromTheme("view-fullscreen"), self.tr("View &All"), self
        )
        self.viewall_action.setStatusTip(self.tr("Zoom out to see the whole file"))
        self.viewall_action.setShortcut("Ctrl+A")
        self.viewall_action.triggered.connect(self.show_all)

        self.recenter_action = QAction(
            QIcon.fromTheme("mail-send"), self.tr("Re-center"), self
        )
        self.recenter_action.setStatusTip(
            self.tr("Center view on the selection, or the mark")
        )
        self.recenter_action.triggered.connect(self.recenter_on_selection)

        self.add_files_action = QAction(self.tr("&Add New Files…"), self)
        self.add_files_action.setStatusTip(
            self.tr(
                "Read new annotations, replacement annotations, talkers or words "
                "into the project database"
            )
        )
        self.add_files_action.triggered.connect(self.add_new_files)

        self.rebuild_action = QAction(self.tr("&Rebuild Project…"), self)
        self.rebuild_action.setStatusTip(
            self.tr("Read all annotation files into a new project database")
        )
        self.rebuild_action.triggered.connect(self.rebuild_project)

        self.rebuild_annotation_action = QAction(
            self.tr("&Reread an annotation file"), self
        )
        self.rebuild_annotation_action.setStatusTip(
            self.tr(
                "Reread the current file's annotation. Other "
                "files' annotations are left as they are"
            )
        )
        self.rebuild_annotation_action.triggered.connect(self.rebuild_annotation)

        # Project Menu
        if mainMenu is not None:
            projectMenu = mainMenu.addMenu(self.tr("&Project"))
        if projectMenu is not None:
            projectMenu.addAction(self.add_files_action)
            projectMenu.addAction(self.rebuild_action)
            projectMenu.addSeparator()
            projectMenu.addAction(self.project_layout_action)
            projectMenu.addAction(self.inspect_database_action)
            projectMenu.addSeparator()
            projectMenu.addAction(self.save_layout_action)
        self.update_project_actions()

        self.add_tiers_action = QAction(self.tr("&Add Tiers…"), self)
        self.add_tiers_action.setStatusTip(
            self.tr("Add annotation tiers to the current file")
        )
        self.add_tiers_action.setEnabled(False)
        self.add_tiers_action.triggered.connect(self.add_tiers)

        self.arrange_tiers_action = QAction(self.tr("&Show and Order Tiers…"), self)
        self.arrange_tiers_action.setStatusTip(
            self.tr("Choose which annotation tiers are shown and in what order")
        )
        self.arrange_tiers_action.setEnabled(False)
        self.arrange_tiers_action.triggered.connect(self.arrange_tiers)

        self.choose_fonts_action = QAction(self.tr("Choose &Fonts…"), self)
        self.choose_fonts_action.setStatusTip(
            self.tr("Choose the fonts for the annotation tiers")
        )
        self.choose_fonts_action.setEnabled(False)
        self.choose_fonts_action.triggered.connect(self.choose_fonts)

        # Annotation Menu
        if settings.enable_annotation and mainMenu is not None:
            annotationMenu = mainMenu.addMenu(self.tr("&Annotation"))
            if annotationMenu is not None:
                annotationMenu.addAction(self.add_tiers_action)
                annotationMenu.addAction(self.arrange_tiers_action)
                annotationMenu.addAction(self.choose_fonts_action)
                annotationMenu.addSeparator()
                annotationMenu.addAction(self.rebuild_annotation_action)
                annotationMenu.addAction(self.export_annotation_action)

        # View Menu
        if mainMenu is not None:
            viewMenu = mainMenu.addMenu("&View")
        if viewMenu is not None:
            viewMenu.addAction(self.waveview_action)
            viewMenu.addAction(self.sgramview_action)
            viewMenu.addAction(self.annotationview_action)
            viewMenu.addAction(self.viewall_action)
            viewMenu.addAction(self.recenter_action)

    def create_toolbar(self):
        """Create application toolbar"""
        toolbar = QToolBar("Main ToolBar")
        self.addToolBar(toolbar)
        toolbar.setIconSize(QSize(16, 16))

        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addAction(self.waveview_action)
        toolbar.addAction(self.sgramview_action)
        if settings.enable_annotation:
            toolbar.addAction(self.annotationview_action)
        toolbar.addAction(self.viewall_action)
        toolbar.addAction(self.recenter_action)

        toolbar.addSeparator()
        self.play_action = QAction(
            QIcon.fromTheme("media-playback-start"), self.tr("&Play"), self
        )
        self.play_action.setStatusTip(self.tr("Play visible audio"))
        self.play_action.triggered.connect(self.play_visible)
        toolbar.addAction(self.play_action)

        self.stop_action = QAction(
            QIcon.fromTheme("media-playback-stop"), self.tr("&Stop"), self
        )
        self.stop_action.setStatusTip(self.tr("Stop audio playback"))
        self.stop_action.triggered.connect(self.stop_audio)
        toolbar.addAction(self.stop_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.exit_action)

    def get_current_document(self) -> DocumentView | None:
        """Get the currently active DocumentView"""
        current_widget = self.tab_widget.currentWidget()
        if isinstance(current_widget, DocumentView):
            return current_widget
        return None

    @pyqtSlot(object)
    def on_doc_state_change(self, state: State):
        if isinstance(state, AudioPrepped):
            self.sgramview_action.setEnabled(True)
        elif isinstance(state, TierSearchAction):
            self.open_tier_search(state)
        elif isinstance(state, ArrangeTiersAction):
            self.arrange_tiers()

    def open_tier_search(self, action: TierSearchAction):
        """Show the search window for the tier, which stays open as the user moves
        between files, so it belongs to the window rather than to any one document"""
        dir_path = self.view_model.dir_path
        if self.tier_search_dialog is None or self.tier_search_dir_path != dir_path:
            if self.tier_search_dialog is not None:
                self.tier_search_dialog.close()
            view_model = self.view_model_factory.create(TierSearchViewModel, dir_path)
            view_model.subscribe(self.on_tier_search_state_change)
            self.tier_search_dialog = TierSearchDialog(view_model, self)
            self.tier_search_dir_path = dir_path

        self.tier_search_dialog.view_model.set_target(
            action.tier_name, action.file_stem, action.start
        )
        self.tier_search_dialog.show_and_focus()

    @pyqtSlot(object)
    def on_tier_search_state_change(self, state: State):
        if isinstance(state, TierSearchMatchState):
            self.show_tier_match(state)
        elif isinstance(state, TierLabelsChangedState):
            for doc in self.documents():
                if doc.view_model.file_stem in state.file_stems:
                    doc.view_model.reload_annotation()

    def documents(self) -> list[DocumentView]:
        widgets = (self.tab_widget.widget(i) for i in range(self.tab_widget.count()))
        return [widget for widget in widgets if isinstance(widget, DocumentView)]

    def show_tier_match(self, match: TierSearchMatchState):
        """Bring the matching label into view, opening its file if it isn't open"""
        doc = self.find_document(match.file_stem)
        if doc is None:
            doc = self.open_project_document(match.file_stem)
        if doc is None:
            return

        self.tab_widget.setCurrentWidget(doc)
        doc.view_model.reveal_span(match.start, match.end)

    def find_document(self, file_stem: str) -> DocumentView | None:
        return next(
            (doc for doc in self.documents() if doc.view_model.file_stem == file_stem),
            None,
        )

    def open_project_document(self, file_stem: str) -> DocumentView | None:
        dir_path = self.view_model.dir_path
        project_file = next(
            (
                file
                for file in (self.view_model.project_files() if dir_path else [])
                if file.file_stem == file_stem
            ),
            None,
        )
        if (
            dir_path is None
            or project_file is None
            or not Path(project_file.audio_file).exists()
        ):
            QMessageBox.information(
                self,
                self.tr("Search in Tier"),
                self.tr("Cannot open the audio file for this match: {}").format(
                    Path(dir_path or "") / f"{file_stem}.wav"
                ),
            )
            return None

        # The annotation is already in the project database, so no TextGrid is given
        self.open_files([project_file._replace(annotation_file=None)], dir_path)
        return self.find_document(file_stem)

    def open_project(self, dir_path: str):
        """Open a directory as a project, closing the project that is open"""
        has_config = (Path(dir_path) / "phonlab.toml").exists()
        if not has_config:
            answer = QMessageBox.question(
                self,
                self.tr("Initialize Project"),
                self.tr("Make a project out of this folder?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.select_path_to_open()
                return

        # A project replaces whatever is open: only one project database is open at
        # a time, and files opened on their own do not belong beside its files
        self.close_project()
        self.close_all_tabs()
        self.view_model.set_dir_path(dir_path)
        if not has_config:
            self.view_model.init_toml()

        if self.view_model.is_new_project():
            # First time here: settle how the project is organized, then build the
            # project database from its files
            if not self.review_project_layout(dir_path):
                self.close_project()
                return
            self.run_project_import(
                self.view_model.add_project_files,
                lambda state: self.open_new_project(dir_path, state),
                self.tr("Importing the project database"),
            )
        else:
            self.open_project_files(dir_path)

    def close_all_tabs(self):
        for index in reversed(range(self.tab_widget.count())):
            self.close_tab(index)

    def close_project(self):
        """Close the project's tabs and its database. Documents that do not belong to
        the project stay open"""
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        for index in reversed(range(self.tab_widget.count())):
            doc = self.tab_widget.widget(index)
            if isinstance(doc, DocumentView) and doc.view_model.dir_path == dir_path:
                self.close_tab(index)

        if self.tier_search_dialog is not None:
            self.tier_search_dialog.close()
            self.tier_search_dialog = None
            self.tier_search_dir_path = None

        if self.database_dialog is not None:
            self.database_dialog.close()
            self.database_dialog = None

        self.view_model.close_project()
        self.save_layout_action.setEnabled(False)
        self.update_project_actions()

    def open_project_files(self, dir_path: str):
        """Open the project's audio files. Annotation files are not read: once a project has
        a database it holds the annotations, and Project > Rebuild re-reads them"""
        files = [
            file._replace(annotation_file=None)
            for file in self.view_model.project_files()
        ]
        self.open_files(files, dir_path)

    def open_new_project(self, dir_path: str, state: ProjectImportState):
        """Report what was found in the new project's annotation files, then open its files"""
        if len(state.failed) > 0:
            QMessageBox.warning(
                self, self.tr("Project"), self.describe_new_project(state)
            )
        elif state.total > 0:
            QMessageBox.information(
                self, self.tr("Project"), self.describe_new_project(state)
            )
        self.open_project_files(dir_path)

    def update_project_actions(self):
        """Project menu items only apply once a project directory is open"""
        has_project = self.view_model.dir_path is not None
        self.add_files_action.setEnabled(has_project)
        self.rebuild_action.setEnabled(has_project)
        self.project_layout_action.setEnabled(has_project)
        self.inspect_database_action.setEnabled(has_project)
        doc = self.get_current_document()
        self.rebuild_annotation_action.setEnabled(
            has_project and doc is not None and doc.view_model.file_stem is not None
        )

    @pyqtSlot()
    def add_new_files(self):
        """Ask what to read into the project database, and do it"""
        choice = AddToProjectDialog.get_choice(self)
        if choice == NEW_ANNOTATIONS:
            self.add_new_annotations()
        elif choice == REPLACEMENT_ANNOTATIONS:
            self.replace_annotations()
        elif choice == TALKERS:
            self.add_talkers()
        elif choice == WORDS:
            self.add_words()

    def add_new_annotations(self):
        """Read the TextGrids that are not in the database yet, with the audio files
        they belong to"""

        def headline(state: ProjectImportState) -> str:
            if state.registered == 0 and len(state.imported) == 0:
                return self.tr("There are no new annotations to add.")
            return self.tr("Added {} new files and read {} annotation files.").format(
                state.registered, len(state.imported)
            )

        self.run_project_import(
            self.view_model.add_project_files,
            lambda state: self.finish_project_update(state, headline(state)),
        )

    def replace_annotations(self):
        """Read TextGrids the user chooses again, replacing the database's annotations
        for them"""
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("Choose the annotation files to read again"),
            dir_path,
            self.tr(
                "Annotation files (*.TextGrid *.textgrid *.eaf *.srt *.cha);;All files (*)"
            ),
        )
        if len(paths) == 0:
            return

        answer = QMessageBox.question(
            self,
            self.tr("Replacement Annotations"),
            self.tr(
                "Replace the annotations the project database has for {} annotation files? "
                "Changes made in the database that were not saved to a file will be left "
                "out."
            ).format(len(paths)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def headline(state: ProjectImportState) -> str:
            lines = [
                self.tr("Replaced the annotations for {} annotation files.").format(
                    len(state.imported)
                )
            ]
            skipped = len(paths) - state.total
            if skipped > 0:
                lines.append(
                    self.tr(
                        "{} of the files chosen are not matched with a "
                        "recording in the project, and were left out."
                    ).format(skipped)
                )
            return "\n".join(lines)

        self.run_project_import(
            lambda: self.view_model.replace_annotations(paths),
            lambda state: self.finish_project_update(state, headline(state)),
            self.tr("Replacing annotations"),
        )

    def add_words(self):
        """Make the word table of the project database from a table with a row for each
        word, and say how many of the words of a tier it has"""
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        csv_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose a table of words"),
            dir_path,
            self.tr("CSV files (*.csv *.tsv *.txt);;All files (*)"),
        )
        if csv_path == "":
            return

        view_model = self.view_model_factory.create(
            WordImportViewModel, dir_path, csv_path
        )
        try:
            view_model.prepare()
        except (ValueError, OSError) as err:
            QMessageBox.critical(self, self.tr("Add Words"), str(err))
            return

        dialog = WordImportDialog(view_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, self.tr("Add Words"), dialog.result_text)

    @pyqtSlot()
    def rebuild_project(self):
        answer = QMessageBox.question(
            self,
            self.tr("Rebuild Project"),
            self.tr(
                "Rebuild the project database from the TextGrids in {}? Annotation "
                "changes that were not saved to a TextGrid will be left out. The "
                "current database is kept as a backup."
            ).format(self.view_model.dir_path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.run_project_import(
            self.view_model.rebuild_project,
            lambda state: self.finish_project_update(
                state, self.tr("The project database has been rebuilt.")
            ),
            self.tr("Rebuilding the project database"),
        )

    @pyqtSlot()
    def rebuild_annotation(self):
        """Replace the current file's annotation with the one in its TextGrid. Only
        this file's entries are removed from the database; the rest is untouched"""
        doc = self.get_current_document()
        if doc is None or doc.view_model.file_stem is None:
            return

        textgrid_file = self.view_model.textgrid_for(doc.view_model.file_stem)
        if textgrid_file is None:
            QMessageBox.information(
                self,
                self.tr("Rebuild Annotation"),
                self.tr("There is no TextGrid for {} in the project directory.").format(
                    doc.view_model.file_stem
                ),
            )
            return

        overwrite = doc.view_model.has_annotation()
        if overwrite:
            answer = ask_overwrite_annotation(self, textgrid_file)
            if answer != QMessageBox.StandardButton.Yes:
                return

        doc.load_textgrid(textgrid_file, overwrite)

    def run_project_import(
        self,
        start: Callable[[], None],
        on_finished: Callable[[ProjectImportState], None],
        title: str = "",
    ):
        self.on_import_finished = on_finished
        self.import_title = title or self.tr("Updating the project database")
        start()

    def finish_project_update(self, state: ProjectImportState, headline: str):
        """Show the database's current annotations in the open tabs, and report: the
        headline, and what went wrong, if anything"""
        for index in range(self.tab_widget.count()):
            doc = self.tab_widget.widget(index)
            if isinstance(doc, DocumentView):
                doc.view_model.reload_annotation()

        QMessageBox.information(
            self,
            self.tr("Project"),
            "\n".join(
                [
                    headline,
                    *self.describe_information(state),
                    *self.describe_failures(state),
                ]
            ),
        )

    def describe_information(self, state: ProjectImportState) -> list[str]:
        """What went wrong when a rebuild added the information from CSV files again"""
        if len(state.information_failed) == 0:
            return []
        return [
            self.tr(
                "Could not add the information from {}: the file is missing or no "
                "longer fits the project."
            ).format(", ".join(state.information_failed))
        ]

    def describe_new_project(self, state: ProjectImportState) -> str:
        lines = [
            self.tr("Found {} annotation files and built the project database.").format(
                state.total
            )
        ]
        return "\n".join(lines + self.describe_failures(state))

    def describe_failures(self, state: ProjectImportState) -> list[str]:
        if len(state.failed) == 0:
            return []
        return [
            self.tr("Could not read the annotation file for: {}").format(
                ", ".join(state.failed)
            )
        ]

    @pyqtSlot(object)
    def on_view_model_state_changed(self, state: State):
        if not isinstance(state, ProjectImportState):
            return

        if not state.finished:
            self.show_import_progress(state)
            return

        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None

        on_finished, self.on_import_finished = self.on_import_finished, None
        if state.error is not None:
            QMessageBox.warning(
                self,
                self.tr("Project"),
                self.tr("Could not update the project database: {}").format(
                    state.error
                ),
            )
        elif on_finished is not None:
            on_finished(state)

    def show_import_progress(self, state: ProjectImportState):
        """Tells the user what the long run of building the database is doing: which
        step, and while annotation files are read, how far along and which file"""
        dialog = self.progress_dialog
        if dialog is None:
            dialog = QProgressDialog("", "", 0, 0, self)
            dialog.setWindowTitle(self.import_title)
            dialog.setCancelButton(None)
            dialog.setWindowModality(Qt.WindowModality.WindowModal)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.setMinimumDuration(0)
            dialog.setMinimumWidth(460)
            self.progress_dialog = dialog

        if state.stage is ImportStageState.READING and state.total > 0:
            dialog.setRange(0, state.total)
            dialog.setValue(state.done)
            # Always two lines: a box that has shrunk to one line (between two files)
            # does not grow again for the next file's name
            dialog.setLabelText(
                self.tr("Reading annotations: {} of {} done").format(
                    state.done, state.total
                )
                + "\n"
                + (
                    self.tr("Now reading {}").format(state.current)
                    if state.current
                    else " "
                )
            )
            return

        # steps whose length is not known show a busy indicator
        dialog.setRange(0, 0)
        dialog.setLabelText(
            {
                ImportStageState.SCANNING: self.tr(
                    "Looking through the project's files…"
                ),
                ImportStageState.REGISTERING: self.tr(
                    "Recording the files in the database…"
                ),
                ImportStageState.INFORMATION: self.tr(
                    "Adding information from the CSV files…"
                ),
                ImportStageState.READING: self.tr("Reading annotations…"),
            }[state.stage]
        )

    def review_project_layout(self, dir_path: str, force_review: bool = False) -> bool:
        """Settle how the project's folders and files are organized, asking the user
        when there is something to decide, and save it in the project. Returns False
        if the user cancelled"""
        layout_view_model = self.view_model_factory.create(
            ProjectLayoutViewModel, dir_path
        )
        try:
            return ProjectLayoutDialog.review_layout(
                layout_view_model, self, force_review
            )
        except Exception as err:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Project Layout"), str(err))
            return False

    @pyqtSlot()
    def edit_project_layout(self):
        """Review the layout, then bring the project database up to date with it"""
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        if not self.review_project_layout(dir_path, force_review=True):
            return

        self.run_project_import(
            self.view_model.add_project_files,
            lambda state: self.finish_project_update(
                state, self.tr("The project layout has been applied.")
            ),
            self.tr("Applying the project layout"),
        )

    def add_talkers(self):
        """Add the columns of a table with a line for each talker to the talker table"""
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        csv_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose a CSV file"),
            dir_path,
            self.tr("CSV files (*.csv *.tsv *.txt);;All files (*)"),
        )
        if csv_path == "":
            return

        view_model = self.view_model_factory.create(
            MetadataImportViewModel,
            dir_path,
            csv_path,
            target=MetadataTarget.TALKER,
        )
        try:
            view_model.prepare()
        except (ValueError, OSError) as err:
            QMessageBox.critical(self, self.tr("Add Information from CSV"), str(err))
            return

        dialog = MetadataImportDialog(view_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self, self.tr("Add Information from CSV"), dialog.result_text
            )

    @pyqtSlot()
    def inspect_database(self):
        dir_path = self.view_model.dir_path
        if dir_path is None:
            return

        view_model = self.view_model_factory.create(DatabaseViewModel, dir_path)
        try:
            view_model.prepare()
        except Exception as err:  # noqa: BLE001
            QMessageBox.critical(self, self.tr("Project Database"), str(err))
            return

        if self.database_dialog is not None:
            self.database_dialog.close()  # one window for the database at a time
        dialog = DatabaseDialog(view_model, self)
        # the window deletes itself when it is closed, so it must not be used after
        dialog.destroyed.connect(
            lambda _=None, closed=dialog: self.forget_database_dialog(closed)
        )
        self.database_dialog = dialog
        dialog.show()

    def forget_database_dialog(self, dialog: DatabaseDialog):
        if self.database_dialog is dialog:
            self.database_dialog = None

    def open_paths(self, paths: list[str]):
        """Open what the user chose: a lone directory, or a project's phonlab.toml or
        phonlab.db file, is a project; anything else is the sound file (and its
        TextGrid) of a document"""
        if len(paths) == 1 and Path(paths[0]).is_dir():
            self.open_project(paths[0])
        elif len(paths) == 1 and Path(paths[0]).name in PROJECT_MARKER_FILES:
            self.open_project(str(Path(paths[0]).parent))
        else:
            self.open_single_document(paths, self.view_model.dir_path)

    def open_single_document(self, filenames: list[str], dir: str | None = None):
        """Open a sound file, with its TextGrid, ELAN or subtitle file if given. A file
        in the project directory `dir` is part of the project; one anywhere else is
        opened on its own, which closes the project, and is offered the annotation
        file named like it in its folder if none is given"""
        audio_files = [name for name in filenames if is_audio_file(name)]
        annotation_files = [name for name in filenames if is_annotation_file(name)]
        if len(audio_files) == 0:
            raise ValueError(self.tr("Please include a .wav file"))
        if len(audio_files) > 1 or len(annotation_files) > 1:
            raise ValueError(
                self.tr("Cannot select more than one .wav file and one annotation file")
            )

        audio_file = audio_files[0]
        if dir is not None and not Path(audio_file).is_relative_to(dir):
            self.close_project()
            dir = None

        if dir is None:
            file_stem = Path(audio_file).with_suffix("").as_posix()
        else:
            file_stem = Path(audio_file).relative_to(dir).with_suffix("").as_posix()

        annotation_file = None
        if len(annotation_files) > 0:
            annotation_file = annotation_files[0]
        elif dir is None:
            # A sound file opened on its own has no project database to take its
            # annotation from, so offer the one that is next to it
            matches = matching_annotation_files(audio_file)
            if matches:
                annotation_file = ask_open_with_annotation(self, audio_file, matches)

        self.open_files([(file_stem, audio_file, annotation_file)], dir)

    def close_splash(self):
        """Take the splash card away; it is only for the start, when nothing is open"""
        if self.splash is not None:
            self.splash.close()
            self.splash = None

    @pyqtSlot()
    def select_path_to_open(self):
        """Ask for a project directory or sound files, starting in the open project"""
        paths = OpenPathDialog.get_paths(
            self,
            self.tr("Open a project directory or sound file"),
            self.view_model.dir_path,
            self.filters,
        )
        if len(paths) == 0:
            return

        # the card would stay on top of the progress box of a project being built
        self.close_splash()
        try:
            self.open_paths(paths)
        except ValueError as err:
            QMessageBox.information(None, self.tr("Error"), str(err))
            self.select_path_to_open()

    def open_files(
        self,
        paired_files: Sequence[tuple[str, str, str | None] | OpenableFile],
        dir_path: str | None,
    ):
        """Open as audio file in separate tabs. paired_files is a list of tuples in the format
        (file_stem, audio_file, annotation_file), where file_stem is the path to the audio file,
        minus the suffix (relative path for project, absolute for ad-hoc singal document
        editing). audio_file and annotation_file are the absolute paths to the respective .wav
        and .TextGrid files. A recording stored as one audio file per channel has a fourth
        element: the absolute paths of those files, in channel order, which are opened as the
        channels of one document"""

        self.view_model.set_dir_path(dir_path)
        self.save_layout_action.setEnabled(dir_path is not None)
        self.update_project_actions()

        # Set by a "to all" answer, so the user is asked at most once per call
        overwrite_all: bool | None = None

        for idx, (file_stem, audio_file, annotation_file, *rest) in enumerate(
            paired_files
        ):
            if idx > 4:
                return
            channel_files = list(rest[0]) if rest else []
            if channel_files:
                n_channels = len(channel_files)
                options = AudioOpenOptionsState(
                    target_fs=DEFAULT_SAMPLE_RATE,
                    channel_mode=(
                        ChannelMode.STEREO
                        if n_channels == 2
                        else ChannelMode.MULTICHANNEL
                    ),
                    retained_channels=list(range(n_channels)),
                    primary_channel=0,
                )
            else:
                options = OpenAudioDialog.get_options(audio_file, self)
            if options is None:
                return

            self.close_splash()

            # Create new document
            doc_view_model = self.view_model_factory.create(
                DocumentViewModel, file_stem, dir_path
            )
            doc_view_model.subscribe(self.on_doc_state_change)
            doc_view_model.set_plots(self.view_model.display_plan)
            self.apply_tier_display(doc_view_model)
            doc = DocumentView(doc_view_model)
            doc.origin_name = (
                Path(file_stem).name if channel_files else Path(audio_file).name
            )
            doc.origin_path = audio_file

            # Add tab with shortened filename
            tab_name = doc.origin_name
            index = self.tab_widget.addTab(doc, tab_name)
            self.tab_widget.setCurrentIndex(index)
            self.tab_widget.setTabToolTip(index, audio_file)

            # Load the audio file
            doc.load_audio(channel_files or audio_file, options)

            if annotation_file is None:
                continue

            overwrite = False
            if doc.view_model.has_annotation():
                # The database already has an annotation for this file
                if overwrite_all is None:
                    answer = ask_overwrite_annotation(
                        self, annotation_file, allow_all=True
                    )
                    if answer == QMessageBox.StandardButton.YesToAll:
                        overwrite_all = True
                    elif answer == QMessageBox.StandardButton.NoToAll:
                        overwrite_all = False
                    overwrite = answer in (
                        QMessageBox.StandardButton.Yes,
                        QMessageBox.StandardButton.YesToAll,
                    )
                else:
                    overwrite = overwrite_all
                if not overwrite:
                    continue

            doc.load_textgrid(annotation_file, overwrite)

    def _open_clip_tab(self, source_doc: DocumentView, clip: AudioState):
        """Open a new tab containing the just-copied/cut samples, without
        stealing focus from source_doc"""
        doc_view_model = self.view_model_factory.create(DocumentViewModel)
        doc_view_model.subscribe(self.on_doc_state_change)
        doc_view_model.set_plots(self.view_model.display_plan)
        self.apply_tier_display(doc_view_model)
        doc_view_model.set_shown(False)  # opened behind the source document
        doc = DocumentView(doc_view_model)

        # Always name after the ORIGINAL source file
        origin_name = source_doc.origin_name
        if not origin_name:
            source_index = self.tab_widget.indexOf(source_doc)
            origin_name = self.tab_widget.tabText(source_index)
        doc.origin_name = origin_name
        doc.origin_path = source_doc.origin_path

        n = self.clip_counters.get(origin_name, 0) + 1
        self.clip_counters[origin_name] = n
        tab_name = self.tr("CLIP {}: {}").format(n, origin_name)
        self.tab_widget.addTab(doc, tab_name)

        doc.view_model.load_from_samples(clip)

    pyqtSlot(int)

    def on_tab_changed(self, index: int):
        self.update_project_actions()
        doc = self.get_current_document()

        self.add_tiers_action.setEnabled(doc is not None)
        self.arrange_tiers_action.setEnabled(doc is not None)
        self.choose_fonts_action.setEnabled(doc is not None)

        # Only the tab on screen computes its spectrogram, a hidden one waits
        for tab_index in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(tab_index)
            if isinstance(tab, DocumentView):
                tab.view_model.set_shown(tab is doc)

        if doc is not None:
            # Every document shows the plots the user last chose
            doc.view_model.set_plots(self.view_model.display_plan)
            self.sgramview_action.setEnabled(
                doc.view_model.spectrogram_view_model.prepped_audio_state is not None
            )

    def save_audio(self):
        doc = self.get_current_document()
        if not doc:
            return
        index = self.tab_widget.indexOf(doc)
        options = SaveAudioDialog.get_options(doc, self.tab_widget.tabText(index), self)
        if options is None:
            return
        try:
            doc.view_model.save_audio(
                options.channels, options.path, options.target_fs, options.scale
            )
        except RuntimeError as err:
            QMessageBox.critical(
                self,
                self.tr("Save Audio"),
                self.tr("Could not save the file:\n{}").format(err),
            )

    @pyqtSlot()
    def add_tiers(self):
        doc = self.get_current_document()
        if doc is None:
            return

        # So the new tiers can be seen
        if not doc.view_model.plot_layout_state.has_annotation():
            self.plot_annotations()
        tiers_before = doc.view_model.tier_names()
        doc.open_add_tiers()

        # Tiers the user just added are meant to be seen
        added = [
            name for name in doc.view_model.tier_names() if name not in tiers_before
        ]
        hidden_tiers = self.view_model.hidden_tiers
        if any(name in hidden_tiers for name in added):
            self.set_tier_display(
                [name for name in hidden_tiers if name not in added],
                self.view_model.tier_order,
            )

    @pyqtSlot()
    def arrange_tiers(self):
        """Ask which tiers to show and in what order, for every document: the tiers
        belong to the project, not to a file"""
        doc = self.get_current_document()
        if doc is None:
            return

        tiers = TierDisplayDialog.get_tiers(doc.view_model.tier_display(), self)
        if tiers is None:
            return

        self.set_tier_display(*hidden_and_order_from(tiers))

        # So the tiers can be seen
        if not doc.view_model.plot_layout_state.has_annotation():
            self.plot_annotations()

    def set_tier_display(self, hidden_tiers: list[str], tier_order: list[str]):
        """Show the tiers this way in every document, and in those opened later"""
        self.view_model.set_tier_display(hidden_tiers, tier_order)
        self.apply_to_documents(self.apply_tier_display)

    def apply_to_documents(self, apply: Callable[[DocumentViewModel], None]):
        for index in range(self.tab_widget.count()):
            tab = self.tab_widget.widget(index)
            if isinstance(tab, DocumentView):
                apply(tab.view_model)

    @pyqtSlot()
    def choose_fonts(self):
        """Ask for the font of the labels of each tier, for every document: the tiers
        belong to the project, not to a file"""
        doc = self.get_current_document()
        if doc is None:
            return

        names = [tier.name for tier in listed_as_plotted(doc.view_model.tier_display())]
        fonts = TierFontDialog.get_fonts(names, self.view_model.tier_fonts, self)
        if fonts is None:
            return

        self.view_model.set_tier_fonts(fonts)
        self.apply_to_documents(self.apply_tier_display)

        # So the labels can be seen
        if not doc.view_model.plot_layout_state.has_annotation():
            self.plot_annotations()

    def apply_tier_display(self, doc_view_model: DocumentViewModel):
        """Make a document show the tiers the way every document does"""
        doc_view_model.set_tier_display(
            self.view_model.hidden_tiers, self.view_model.tier_order
        )
        doc_view_model.set_tier_fonts(self.view_model.tier_fonts)

    def save_textgrid(self):
        doc = self.get_current_document()
        if doc:
            doc.open_save_textgrid()

    def save_window_layout(self):
        try:
            self.view_model.save_window_layout()
        except (OSError, ValueError) as err:
            QMessageBox.critical(
                self,
                self.tr("Save Window Layout"),
                self.tr("Could not save the window layout:\n{}").format(err),
            )
            return
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(self.tr("Window layout saved to project"), 3000)

    def show_audio_info(self):
        doc = self.get_current_document()
        if doc:
            doc.open_audio_info()

    def close_tab(self, index: int):
        """Close a tab"""
        widget = self.tab_widget.widget(index)
        if isinstance(widget, DocumentView):
            widget.cleanup()
        self.tab_widget.removeTab(index)

    def close_current_tab(self):
        """Close the currently active tab"""
        index = self.tab_widget.currentIndex()
        if index >= 0:
            self.close_tab(index)

    # Delegate actions to current document
    def plot_wave(self):
        doc = self.get_current_document()
        if doc:
            doc.toggle_wave()
            self.view_model.set_display_plan(doc.view_model.plot_layout_state.plots)

    def plot_wave_sgram(self):
        doc = self.get_current_document()
        if doc:
            doc.toggle_spectrogram()
            self.view_model.set_display_plan(doc.view_model.plot_layout_state.plots)

    def plot_annotations(self):
        doc = self.get_current_document()
        if doc:
            doc.toggle_annotations()
            self.view_model.set_display_plan(doc.view_model.plot_layout_state.plots)

    def show_all(self):
        doc = self.get_current_document()
        if doc:
            doc.show_all()

    def play_visible(self):
        doc = self.get_current_document()
        if doc:
            doc.play_visible()

    def stop_audio(self):
        doc = self.get_current_document()
        if doc:
            doc.stop_audio()

    def recenter_on_selection(self):
        """Delegate recenter to current document"""
        doc = self.get_current_document()
        if doc:
            doc.recenter_on_selection()

    def copy_selection(self):
        doc = self.get_current_document()
        if doc:
            clip = doc.copy_selection()
            if clip is not None:
                self.clipboard = clip
                self._open_clip_tab(doc, clip)

    def cut_selection(self):
        doc = self.get_current_document()
        if doc:
            clip = doc.cut_selection()
            if clip is not None:
                self.clipboard = clip
                self._open_clip_tab(doc, clip)

    def paste_at_cursor(self):
        doc = self.get_current_document()
        if doc and self.clipboard is not None:
            doc.paste_at_cursor(self.clipboard)

    def paste_special(self):
        doc = self.get_current_document()
        if doc and self.clipboard is not None:
            doc.paste_special(self.clipboard)

    def undo(self):
        doc = self.get_current_document()
        if doc:
            doc.undo()

    def redo(self):
        doc = self.get_current_document()
        if doc:
            doc.redo()

    def keyPressEvent(self, a0: QKeyEvent | None):
        """Forward keyboard events to current document"""
        doc = self.get_current_document()
        if doc is not None and a0 is not None:
            if a0.key() == Qt.Key.Key_Left:
                doc.go_back()
            elif a0.key() == Qt.Key.Key_Right:
                doc.advance()
            elif a0.key() == Qt.Key.Key_Down:
                doc.zoom_out()
            elif a0.key() == Qt.Key.Key_Up:
                doc.zoom_in()
            else:
                super().keyPressEvent(a0)
        else:
            super().keyPressEvent(a0)

    def quit_app(self):
        """Quit the application"""
        # Clean up all open documents
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, DocumentView):
                widget.cleanup()

        self.close()
        QApplication.quit()

    def closeEvent(self, a0: QCloseEvent | None):
        """Handle window close event"""
        # Clean up all open documents
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, DocumentView):
                widget.cleanup()

        if a0 is not None:
            a0.accept()
