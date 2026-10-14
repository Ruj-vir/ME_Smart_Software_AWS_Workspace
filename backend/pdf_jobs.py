"""Temporary PDF jobs for the single-process backend used by docker-compose."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
from uuid import uuid4


class PdfJobs:
    def __init__(self, ttl=1800, capacity=8):
        self.ttl = ttl
        self.capacity = capacity
        self.jobs = {}
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=2)

    def _expire(self):
        now = monotonic()
        for key, job in list(self.jobs.items()):
            if job['finished'] is not None and now - job['finished'] > self.ttl:
                del self.jobs[key]

    def submit(self, work):
        with self.lock:
            self._expire()
            if len(self.jobs) >= self.capacity:
                # Evict the oldest completed result, never an active job.
                completed = [k for k, j in self.jobs.items() if j['finished'] is not None]
                if not completed:
                    raise OverflowError('PDF queue is full. Please try again later.')
                del self.jobs[min(completed, key=lambda k: self.jobs[k]['finished'])]
            key = uuid4().hex
            self.jobs[key] = dict(status='queued', finished=None, data=None, error=None)
        self.executor.submit(self._run, key, work)
        return key

    def _run(self, key, work):
        with self.lock:
            self.jobs[key]['status'] = 'running'
        try:
            data = work()
            result = dict(status='completed', data=data)
        except Exception as exc:
            result = dict(status='failed', error=str(getattr(exc, 'detail', None) or exc))
        with self.lock:
            self.jobs[key].update(result, finished=monotonic())

    def get(self, key):
        with self.lock:
            self._expire()
            job = self.jobs.get(key)
            return dict(job) if job else None
