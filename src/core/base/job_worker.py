from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from core.base.job import Job


class JobWorker(QRunnable):
    def __init__(self, job: Job):
        super().__init__()
        self.slots = JobWorkerSlots(self)
        self.signals = JobWorkerSignals()
        self.job = job
        self.should_stop = False

    def set_job(self, job: Job):
        self.job = job

    def run(self):
        while True:
            if self.job is not None:
                job = self.job
                self.job = None

                self.signals.result.connect(job.on_success)
                self.signals.error.connect(job.on_error)
                try:
                    for result in job.use_case.invoke():
                        self.signals.result.emit(result)
                        if self.should_stop:
                            job.use_case.stop()
                            self.signals.finished.emit()
                            break
                except Exception as err:
                    self.signals.error.emit(err)
                    raise
            else:
                self.signals.finished.emit()
                break


class JobWorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(Exception)
    finished = pyqtSignal()


class JobWorkerSlots(QObject):
    def __init__(self, job_worker: JobWorker):
        super().__init__()
        self.job_worker = job_worker

    @pyqtSlot(object)
    def queue_job(self, job: Job):
        self.job_worker.set_job(job)

    @pyqtSlot()
    def stop(self):
        self.job_worker.should_stop = True
