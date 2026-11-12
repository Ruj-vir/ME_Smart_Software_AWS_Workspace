import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock

from office_sessions import OfficeSessions, OfficeSaveError, SnapshotStore


class OfficeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sessions.sqlite3'
        self.office = OfficeSessions(self.path, timeout=0.05)
        self.name = 'forms/report.xlsx'
        self.etag = lambda: 'original-etag'
        self.read = Mock(return_value=b'original')
        self.save = Mock()
        self.key = self.office.key(self.name, self.etag())

    def callback(self, status, request_id=None, data=b'edited', key=None, **extra):
        body = dict(status=status, key=key or self.key, url='http://office/file',
                    filetype='xlsx', userdata=request_id, **extra)
        self.office.callback(self.name, body, lambda url: data, self.save, self.etag)

    def snapshot(self, command):
        return self.office.snapshot(self.name, self.etag, self.read, command)

    def force(self, data=b'edited'):
        def command(key, request_id):
            self.callback(6, request_id, data=data, key=key)
            return 0
        return self.snapshot(command)

    def test_export_uses_acknowledged_bytes_without_overwriting_live_file(self):
        self.callback(1)
        self.assertEqual(self.force(), (b'edited', 'xlsx'))
        self.save.assert_not_called()
        self.read.assert_not_called()
        self.assertEqual(self.office.key(self.name, 'different-etag'), self.key)

    def test_key_and_confirmed_copy_survive_backend_restart(self):
        self.force()
        self.office = OfficeSessions(self.path)
        self.assertEqual(self.office.key(self.name, 'different'), self.key)
        self.assertEqual(self.snapshot(lambda *args: 4), (b'edited', 'xlsx'))

    def test_document_server_reload_uses_durable_confirmed_copy(self):
        self.force()
        self.office = OfficeSessions(self.path)
        self.assertEqual(self.office.source(self.name, self.read), (b'edited', 'xlsx'))
        self.read.assert_not_called()

    def test_unordered_external_force_save_invalidates_export_fallback(self):
        self.force(data=b'newer')
        self.callback(6, data=b'unknown-order')
        with self.assertRaises(OfficeSaveError):
            self.snapshot(lambda *args: 4)
        # A subsequent acknowledged save restores normal generation.
        self.assertEqual(self.force(data=b'latest'), (b'latest', 'xlsx'))

    def test_external_save_racing_no_change_reply_does_not_allow_fallback(self):
        self.force(data=b'confirmed')
        def command(key, request_id):
            self.callback(6, data=b'unordered')
            return 4
        with self.assertRaises(OfficeSaveError):
            self.snapshot(command)

    def test_save_error_racing_no_change_reply_does_not_allow_fallback(self):
        def command(key, request_id):
            self.callback(7)
            return 4
        with self.assertRaises(OfficeSaveError):
            self.snapshot(command)

    def test_final_save_rotates_key_even_when_etag_unchanged(self):
        self.callback(2, data=b'final')
        self.save.assert_called_once_with(b'final')
        self.assertNotEqual(self.office.key(self.name, self.etag()), self.key)

    def test_force_save_after_final_save_cannot_overwrite_final(self):
        self.callback(2, data=b'final')
        self.callback(6, data=b'old')
        self.save.assert_called_once_with(b'final')

    def test_old_session_callback_cannot_overwrite_new_session(self):
        self.callback(2)
        self.office.key(self.name, 'new-etag')
        with self.assertRaises(OfficeSaveError):
            self.callback(2, data=b'old')
        self.assertEqual(self.save.call_count, 1)

    def test_first_unchanged_open_document_can_use_original(self):
        self.callback(1)
        self.assertEqual(self.snapshot(lambda *args: 4), (b'original', 'xlsx'))

    def test_unopened_document_can_use_original(self):
        self.assertEqual(self.snapshot(lambda *args: 1), (b'original', 'xlsx'))

    def test_missing_active_document_does_not_silently_use_old_original(self):
        self.callback(1)
        with self.assertRaises(OfficeSaveError):
            self.snapshot(lambda *args: 1)
        self.read.assert_not_called()

    def test_timeout_remains_uncertain_across_restart(self):
        with self.assertRaisesRegex(OfficeSaveError, 'Timed out'):
            self.snapshot(lambda *args: 0)
        self.office = OfficeSessions(self.path)
        with self.assertRaises(OfficeSaveError):
            self.snapshot(lambda *args: 4)
        self.read.assert_not_called()

    def test_late_export_callback_after_timeout_never_writes_original(self):
        ids = []
        def command(key, request_id):
            ids.append(request_id)
            return 0
        with self.assertRaises(OfficeSaveError):
            self.snapshot(command)
        self.callback(6, ids[0], data=b'late')
        self.save.assert_not_called()
        self.assertTrue(self.office.state(self.name)['uncertain'])

    def test_wrong_request_callback_cannot_complete_export(self):
        def command(key, request_id):
            self.callback(6, 'me-export:wrong', data=b'wrong')
            return 0
        with self.assertRaisesRegex(OfficeSaveError, 'Timed out'):
            self.snapshot(command)
        self.assertEqual(self.office.pending, {})

    def test_error_and_failed_download_are_not_acknowledged_as_success(self):
        def command(key, request_id):
            self.callback(7, request_id)
            return 0
        with self.assertRaisesRegex(OfficeSaveError, 'could not save'):
            self.snapshot(command)
        with self.assertRaisesRegex(OfficeSaveError, 'empty'):
            self.callback(2, data=b'')
        self.save.assert_not_called()

    def test_storage_failure_keeps_session_open_and_uncertain(self):
        self.save.side_effect = OSError('storage offline')
        with self.assertRaises(OSError):
            self.callback(2)
        self.assertNotEqual(self.office.state(self.name)['state'], 'saved')
        self.assertTrue(self.office.state(self.name)['uncertain'])

    def test_close_during_generate_completes_with_final_bytes(self):
        def command(key, request_id):
            self.callback(2, data=b'final')
            return 0
        self.assertEqual(self.snapshot(command), (b'final', 'xlsx'))

    def test_idle_key_survives_reconnect_but_replaced_file_gets_new_key(self):
        self.callback(4)
        self.assertEqual(self.office.key(self.name, self.etag()), self.key)
        self.assertNotEqual(self.office.key(self.name, 'replacement-etag'), self.key)

    def test_two_exports_wait_independently_without_blocking_callbacks(self):
        self.office.timeout = 3
        started, release = Event(), Event()
        request_ids = []
        def command(key, request_id):
            request_ids.append(request_id)
            started.set()
            if len(request_ids) == 1:
                self.assertTrue(release.wait(3))
            self.callback(6, request_id, data=str(len(request_ids)).encode())
            return 0
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.snapshot, command)
            try:
                self.assertTrue(started.wait(3))
                second = pool.submit(self.snapshot, command)
                # Other editors can still join the same session during a save.
                self.assertEqual(self.office.key(self.name, self.etag()), self.key)
            finally:
                release.set()
            self.assertEqual(first.result(3)[0], b'1')
            self.assertEqual(second.result(3)[0], b'2')
        self.assertEqual(len(set(request_ids)), 2)

    def test_callback_runs_on_another_thread_while_worker_waits(self):
        self.office.timeout = 3
        started = Event()
        ids = []
        def command(key, request_id):
            ids.append(request_id)
            started.set()
            return 0
        with ThreadPoolExecutor(max_workers=1) as pool:
            work = pool.submit(self.snapshot, command)
            self.assertTrue(started.wait(3))
            self.callback(6, ids[0])
            self.assertEqual(work.result(3), (b'edited', 'xlsx'))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_remains_unchanged_until_explicit_cleanup(self):
        store = SnapshotStore()
        first = store.add(b'first', 'xlsx')
        second = store.add(b'second', 'xlsx')
        self.assertNotEqual(first, second)
        self.assertEqual(store.get(first), (b'first', 'xlsx'))
        store.remove(first)
        self.assertIsNone(store.get(first))
        self.assertEqual(store.get(second), (b'second', 'xlsx'))


if __name__ == '__main__':
    unittest.main()
