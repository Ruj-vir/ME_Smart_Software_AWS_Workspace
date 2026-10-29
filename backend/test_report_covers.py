import ast
import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from pypdf import PdfReader, PdfWriter
from report_covers import cover_section, create_cover_pdf

ROOT = Path(__file__).resolve().parent.parent


class ReportCoverTests(unittest.TestCase):
    def test_folder_names_and_version_folders(self):
        self.assertEqual(cover_section('Client/Data/ITP/a.pdf'), ('Client/Data/ITP', 'ITP'))
        self.assertEqual(cover_section('Client/Data/ITP/Nested/a.pdf')[1], 'Nested')
        self.assertEqual(cover_section('Client/Data/a.pdf')[1], 'Data')
        self.assertEqual(cover_section('Client/QAQCStep/MaintenanceRecord/Inspection Sheet/original.xls/version.xls')[1], 'Inspection Sheet')
        self.assertIsNone(cover_section('Client/Other/a.pdf'))

    def test_generated_titles_and_footer(self):
        for title in ['ITP', 'P&ID', 'Photographs', '<Test>', 'Long folder name ' * 15, 'รายงานตรวจสอบ']:
            with self.subTest(title=title):
                data = create_cover_pdf(title, ROOT)
                with pymupdf.open(stream=data, filetype='pdf') as doc:
                    text = doc[0].get_text()
                    self.assertEqual(len(doc), 1)
                    self.assertNotIn('ORGANIZE', text)
                    self.assertIn('GC MAINTENANCE', text)
                    self.assertIn(''.join(title.split()), ''.join(text.split()))

    def test_merge_section_order_and_opt_out(self):
        # Execute the actual merge function without starting external services.
        tree = ast.parse((ROOT / 'backend/server.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_combine_pdf_bytes')
        blank = PdfWriter()
        blank.add_blank_page(width=595, height=842)
        buffer = io.BytesIO()
        blank.write(buffer)
        scope = dict(io=io, PdfReader=PdfReader, PdfWriter=PdfWriter,
                     ThreadPoolExecutor=ThreadPoolExecutor, COMBINE_PDF_MAX_WORKERS=5,
                     CombinePdfRequest=SimpleNamespace, STATIC_DIR=ROOT,
                     cover_section=cover_section, create_cover_pdf=create_cover_pdf,
                     _convert_object_to_pdf_bytes=lambda name: buffer.getvalue())
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'server.py', 'exec'), scope)
        names = ['Client/Data/ITP/a.pdf', 'Client/Data/ITP/b.pdf',
                 'Client/Data/P&ID/a.pdf', 'Client/QAQCStep/MaintenanceRecord/Photographs/a.pdf']
        for enabled, count in [(True, 7), (False, 4)]:
            data = scope['_combine_pdf_bytes'](SimpleNamespace(object_names=names, report_covers=enabled, maintenance_cover=False))
            with pymupdf.open(stream=data, filetype='pdf') as doc:
                self.assertEqual(len(doc), count)
                if enabled:
                    for index, title in [(0, 'ITP'), (3, 'P&ID'), (5, 'Photographs')]:
                        self.assertIn(title, doc[index].get_text())


if __name__ == '__main__':
    unittest.main()
