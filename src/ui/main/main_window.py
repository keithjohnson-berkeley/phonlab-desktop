from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QWidget,
)

from ui.document.document_view import DocumentView
from ui.document.document_view_model import DocumentViewModel
from ui.main.open_audio_dialog import OpenAudioDialog


class MainWindow(QMainWindow):
    def __init__(self, splash=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowTitle("Phonlab")
        self.resize(1200, 800)

        self.filters = "Sound files (*.wav)"
        self.splash = splash

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tab_widget)

        # --------- Menu --------------------
        self.create_menus()

        # ------- toolbar -------------
        self.create_toolbar()

    def create_menus(self):
        """Create application menus"""
        mainMenu = self.menuBar()
        self.style()

        # File Menu
        fileMenu = mainMenu.addMenu("&File")

        self.open_action = QAction(
            QIcon.fromTheme("document-open"), self.tr("&Open"), self
        )
        self.open_action.setStatusTip(self.tr("Open a sound file"))
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_file)
        fileMenu.addAction(self.open_action)

        self.close_action = QAction(
            QIcon.fromTheme("window-close"), self.tr("&Close"), self
        )
        self.close_action.setStatusTip(self.tr("Close current file"))
        self.close_action.setShortcut("Ctrl-W")
        self.close_action.triggered.connect(self.close_current_tab)
        fileMenu.addAction(self.close_action)

        fileMenu.addSeparator()

        self.exit_action = QAction(
            QIcon.fromTheme("application-exit"), self.tr("&Quit"), self
        )
        self.exit_action.setStatusTip(self.tr("Terminate the program"))
        self.exit_action.triggered.connect(self.quit_app)
        fileMenu.addAction(self.exit_action)

        # Edit Menu
        mainMenu.addMenu("&Edit")

        # View Menu
        viewMenu = mainMenu.addMenu("&View")

        self.waveview_action = QAction(
            QIcon.fromTheme("audio-x-generic"), self.tr("&Wave"), self
        )
        self.waveview_action.setStatusTip(self.tr("View audio waveform"))
        self.waveview_action.setShortcut("Ctrl+1")
        self.waveview_action.triggered.connect(self.plot_wave)
        viewMenu.addAction(self.waveview_action)

        self.sgramview_action = QAction(
            QIcon.fromTheme("view-media-visualization"), self.tr("&Spectrogram"), self
        )
        self.sgramview_action.setStatusTip(self.tr("View waveform and spectrogram"))
        self.sgramview_action.setShortcut("Ctrl+2")
        self.sgramview_action.triggered.connect(self.plot_wave_sgram)
        viewMenu.addAction(self.sgramview_action)

        self.viewall_action = QAction(
            QIcon.fromTheme("view-fullscreen"), self.tr("View &All"), self
        )
        self.viewall_action.setStatusTip(self.tr("Zoom out to see the whole file"))
        self.viewall_action.setShortcut("Ctrl+A")
        self.viewall_action.triggered.connect(self.show_all)
        viewMenu.addAction(self.viewall_action)

        self.recenter_action = QAction(
            QIcon.fromTheme("mail-send"), self.tr("Re-center"), self
        )
        self.recenter_action.setStatusTip(self.tr("Center view on selection"))
        self.recenter_action.triggered.connect(self.recenter_on_selection)
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

    def get_current_document(self):
        """Get the currently active AudioView"""
        current_widget = self.tab_widget.currentWidget()
        if isinstance(current_widget, DocumentView):
            return current_widget
        return None

    def open_file(self, filename=None):
        """Open a new audio file in a new tab"""
        if not filename:
            filename, _ = QFileDialog.getOpenFileName(self, filter=self.filters)

        if filename:
            options = OpenAudioDialog.get_options(filename, self)
            if options is None:
                return

            if self.splash is not None:
                self.splash.close()
                self.splash = None

            # Create new document
            doc = DocumentView(DocumentViewModel())

            # Add tab with shortened filename
            tab_name = Path(filename).name
            index = self.tab_widget.addTab(doc, tab_name)
            self.tab_widget.setCurrentIndex(index)
            self.tab_widget.setTabToolTip(index, filename)

            # Load the audio file
            doc.load_audio(filename, options)

    def close_tab(self, index):
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

    def on_tab_changed(self, index):
        """Called when the active tab changes"""

    # Delegate actions to current document
    def plot_wave(self):
        doc = self.get_current_document()
        if doc:
            doc.show_spectrogram(False)

    def plot_wave_sgram(self):
        doc = self.get_current_document()
        if doc:
            doc.show_spectrogram(True)

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

    def keyPressEvent(self, event):
        """Forward keyboard events to current document"""
        doc = self.get_current_document()
        if doc:
            if event.key() == Qt.Key.Key_Left:
                doc.go_back()
            elif event.key() == Qt.Key.Key_Right:
                doc.advance()
            elif event.key() == Qt.Key.Key_Down:
                doc.zoom_out()
            elif event.key() == Qt.Key.Key_Up:
                doc.zoom_in()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def quit_app(self):
        """Quit the application"""
        # Clean up all open documents
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, DocumentView):
                widget.cleanup()

        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        """Handle window close event"""
        # Clean up all open documents
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, DocumentView):
                widget.cleanup()

        event.accept()
