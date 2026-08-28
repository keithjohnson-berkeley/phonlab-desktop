from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from core.base.job import Job
from core.base.job_manager import JobManager
from core.base.use_case import UseCase


class ViewModel(QObject):
    state_changed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.job_managers: dict[str, JobManager] = {}

    def subscribe(self, slot: Callable):
        self.state_changed.connect(slot)

    def launch_use_case(
        self,
        key: str,
        use_case: UseCase,
        on_success: Callable,
        on_error: Callable,
        only_once: bool = False,
    ):
        if key in self.job_managers:
            if only_once:
                return
            self.job_managers[key].queue_job(Job(use_case, on_success, on_error))
        else:
            self.job_managers[key] = JobManager()
            self.job_managers[key](Job(use_case, on_success, on_error))

            @pyqtSlot()
            def on_finished():
                del self.job_managers[key]

            self.job_managers[key].signals.finished.connect(on_finished)

    def close_threads(self):
        for key in self.job_managers:
            self.job_managers[key].quit()

    def close_thread(self, key):
        if key in self.job_managers:
            self.job_managers[key].quit()
