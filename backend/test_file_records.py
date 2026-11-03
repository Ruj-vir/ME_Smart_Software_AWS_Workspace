"""Route-level regression checks without requiring live storage services."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class FileRecordTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path(__file__).with_name('server.py').read_text(encoding='utf-8'))
        functions = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in (
                'copy_file', 'upsert_file_record', 'migrate_file_record_dates'
            ):
                node.decorator_list = []
                functions.append(node)
        self.db = MagicMock()
        self.cur = self.db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.mc = MagicMock()
        self.ns = dict(db=self.db, mc=self.mc, MINIO_BUCKET='test',
                       CopyFile=object, FileRecordIn=object, S3Error=RuntimeError,
                       HTTPException=lambda *args: RuntimeError(*args))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'server.py', 'exec'), self.ns)

    def copy(self, folder):
        body = SimpleNamespace(src_object='source.xls', dst_object=f'Client/QAQCStep/MaintenanceRecord/{folder}/version.xls')
        module = SimpleNamespace(CopySource=lambda *args: args)
        with patch.dict('sys.modules', {'minio.commonconfig': module}):
            self.ns['copy_file'](body)

    def test_creation_date_only_for_three_report_types(self):
        for folder in ('MaintenanceReport', 'Spare Part', 'Photographs'):
            self.cur.reset_mock()
            self.copy(folder)
            sql, params = self.cur.execute.call_args.args
            self.assertIn('recorded_at', sql)
            self.assertIn('NOW()', sql)
            self.assertIn('ON CONFLICT (object_name) DO NOTHING', sql)
            self.assertTrue(params[0].endswith('/version.xls'))
        self.cur.reset_mock()
        self.copy('Inspection Sheet/original.xls')
        self.cur.execute.assert_not_called()

    def test_save_names_never_updates_creation_date(self):
        body = SimpleNamespace(object_name='version.xls', by='Recorder', modify_by='Editor',
                               object_type='Turbine', manufacturer='GE', year='2026')
        self.ns['upsert_file_record'](body)
        sql, params = self.cur.execute.call_args.args
        self.assertNotIn('recorded_at', sql)
        self.assertIn('modify_by = EXCLUDED.modify_by', sql)
        self.assertEqual(params[1:3], ('Recorder', 'Editor'))

    def test_ndt_categories_capture_creation_date(self):
        for folder in ('Penetrant Testing Report', 'Ultrasonic Testing Report',
                       'Magnetic Particle Testing Report', 'Hardness Testing Report',
                       'Ultrasonic Thickness Measurement Report', 'Other'):
            self.cur.reset_mock()
            body = SimpleNamespace(src_object='source.xls',
                                   dst_object=f'Client/QAQCStep/NDT Report/{folder}/version.xls')
            with patch.dict('sys.modules', {'minio.commonconfig': SimpleNamespace(CopySource=lambda *args: args)}):
                self.ns['copy_file'](body)
            self.assertIn('recorded_at', self.cur.execute.call_args.args[0])

    def test_failed_copy_does_not_record_creation(self):
        self.mc.copy_object.side_effect = RuntimeError('Copy failed')
        with self.assertRaises(RuntimeError):
            self.copy('MaintenanceReport')
        self.cur.execute.assert_not_called()

    def test_migration_leaves_legacy_dates_unknown(self):
        self.ns['migrate_file_record_dates']()
        statements = [call.args[0] for call in self.cur.execute.call_args_list]
        self.assertTrue(all('IF NOT EXISTS' in sql for sql in statements))
        date_sql = next(sql for sql in statements if 'recorded_at' in sql)
        self.assertNotIn('DEFAULT', date_sql)


if __name__ == '__main__':
    unittest.main()
