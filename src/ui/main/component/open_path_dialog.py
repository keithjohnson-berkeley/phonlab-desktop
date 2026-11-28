from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QWidget,
)


class OpenPathDialog(QFileDialog):
    """File dialog to open sound and TextGrid files, or a project.

    Opening a directory shows what is in it, so the user can look before choosing.
    A project is chosen with the "Open Folder as Project" button, which takes the
    selected directory, or the one being shown if none is selected. Opening a
    project's phonlab.toml or phonlab.db file chooses the directory that holds it
    (that is up to the caller). It is not the native dialog because that cannot
    have the extra button"""

    def __init__(
        self,
        parent: QWidget | None = None,
        caption: str = "",
        directory: str = "",
        filter: str = "",
    ):
        super().__init__(parent, caption, directory, filter)
        self.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.setOption(QFileDialog.Option.DontUseNativeDialog)

        self.project_dir: str | None = None

        # The filter still lists only the files that can be opened, but there is
        # nothing to choose from, so leave out the box to pick one
        for name, type in (("fileTypeCombo", QComboBox), ("fileTypeLabel", QLabel)):
            widget = self.findChild(type, name)
            if widget is not None:
                widget.hide()

        self.open_project_btn = None
        button_box = self.findChild(QDialogButtonBox)
        if button_box is not None:
            self.open_project_btn = button_box.addButton(
                self.tr("Open Folder as Project"),
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            if self.open_project_btn is not None:
                self.open_project_btn.setAutoDefault(False)
                self.open_project_btn.clicked.connect(self.open_folder_as_project)

    def open_folder_as_project(self):
        """Choose the selected directory as the project, or else the one being shown"""
        selected = self.selectedFiles()
        if len(selected) == 1 and Path(selected[0]).is_dir():
            self.project_dir = selected[0]
        else:
            self.project_dir = self.directory().absolutePath()
        QDialog.accept(self)

    @staticmethod
    def get_paths(
        parent: QWidget | None = None,
        caption: str = "",
        directory: str | None = None,
        filter: str = "",
    ) -> list[str]:
        """The project directory or the files the user chose, empty if they cancelled"""
        dialog = OpenPathDialog(parent, caption, directory or "", filter)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []
        if dialog.project_dir is not None:
            return [dialog.project_dir]
        return dialog.selectedFiles()
