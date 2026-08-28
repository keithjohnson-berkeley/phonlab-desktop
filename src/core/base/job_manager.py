from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from core.base.job import Job
from core.base.job_worker import JobWorker


class JobManager:
    thread_pool: QThreadPool = QThreadPool.globalInstance()

    def __init__(self):
        self.signals = JobManagerSignals()

    def __call__(self, job: Job):
        self.worker = JobWorker(job)
        self.thread_pool.start(self.worker)

        self.worker.signals.finished.connect(self.signals.finished)

        self.signals.job.connect(self.worker.slots.queue_job)
        self.signals.should_stop.connect(self.worker.slots.stop)

    def queue_job(self, job: Job):
        self.signals.job.emit(job)

    def quit(self):
        self.signals.job.emit(None)
        self.signals.should_stop.emit()


class JobManagerSignals(QObject):
    job = pyqtSignal(object)
    should_stop = pyqtSignal()
    finished = pyqtSignal()
