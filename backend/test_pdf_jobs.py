import unittest
from threading import Event
from time import monotonic, sleep

from pdf_jobs import PdfJobs


class PdfJobsTests(unittest.TestCase):
    def setUp(self):
        self.jobs = PdfJobs()

    def tearDown(self):
        self.jobs.executor.shutdown(wait=True)

    def finished(self, key):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            job = self.jobs.get(key)
            if job['status'] in ('completed', 'failed'):
                return job
            sleep(0.01)
        self.fail('Job did not finish')

    def test_submission_returns_while_conversion_is_blocked(self):
        release = Event()
        try:
            key = self.jobs.submit(lambda: release.wait(3) and b'%PDF-result')
            self.assertIn(self.jobs.get(key)['status'], ('queued', 'running'))
        finally:
            release.set()
        self.assertEqual(self.finished(key)['data'], b'%PDF-result')

    def test_conversion_failure_is_reported(self):
        def fail():
            raise ValueError('conversion failed')
        job = self.finished(self.jobs.submit(fail))
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['error'], 'conversion failed')

    def test_active_jobs_cannot_be_evicted(self):
        self.jobs.capacity = 1
        release = Event()
        try:
            self.jobs.submit(lambda: release.wait(3))
            with self.assertRaises(OverflowError):
                self.jobs.submit(lambda: b'other')
        finally:
            release.set()

    def test_completed_job_expires(self):
        key = self.jobs.submit(lambda: b'pdf')
        self.finished(key)
        self.jobs.ttl = -1
        self.assertIsNone(self.jobs.get(key))

    def test_old_completed_result_can_be_replaced(self):
        self.jobs.capacity = 1
        old = self.jobs.submit(lambda: b'old')
        self.finished(old)
        new = self.jobs.submit(lambda: b'new')
        self.assertEqual(self.finished(new)['data'], b'new')
        self.assertIsNone(self.jobs.get(old))


if __name__ == '__main__':
    unittest.main()
