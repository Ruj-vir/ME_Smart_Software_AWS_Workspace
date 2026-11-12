"""Exercise the actual route functions against simulated storage/Document Server."""
import ast
import hashlib
import io
import json
import logging
import mimetypes
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import Response, JSONResponse
import jwt
from pypdf import PdfReader, PdfWriter
from starlette.concurrency import run_in_threadpool

from office_sessions import SnapshotStore


def route_scope():
    tree = ast.parse(Path(__file__).with_name('server.py').read_text(encoding='utf-8'))
    names = {'_combine_pdf_bytes', '_convert_object_to_pdf_bytes', '_office_force_save',
             '_office_download', 'onlyoffice_snapshot_download', 'onlyoffice_callback'}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    scope = dict(__name__='office_integration_test', io=io, hashlib=hashlib, uuid=uuid,
                 mimetypes=mimetypes, jwt=jwt, logging=Mock(), Request=Request,
                 Response=Response, JSONResponse=JSONResponse, HTTPException=HTTPException,
                 run_in_threadpool=run_in_threadpool, CombinePdfRequest=SimpleNamespace,
                 ThreadPoolExecutor=ThreadPoolExecutor, COMBINE_PDF_MAX_WORKERS=5,
                 office_conversion_slots=BoundedSemaphore(5),
                 ONLYOFFICE_DOC_TYPES={'xlsx': 'cell', 'xls': 'cell'},
                 ONLYOFFICE_JWT_SECRET='test-secret-with-at-least-32-bytes',
                 ONLYOFFICE_BACKEND_URL='http://backend', ONLYOFFICE_CONVERT_BASE='http://office',
                 ONLYOFFICE_DOCSERVER_URL='http://office',
                 office_snapshots=SnapshotStore(), requests=Mock(),
                 PdfWriter=PdfWriter, PdfReader=PdfReader,
                 cover_section=lambda name: None, fit_pages_to_a4=lambda data: data,
                 _read_object=Mock(return_value=b'original'), _object_etag=Mock(return_value='etag'),
                 office_sessions=Mock(), _save_onlyoffice_callback=Mock())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'server.py', 'exec'), scope)
    return scope


def pdf_bytes(width=595):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=842)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class OfficeConversionTests(unittest.TestCase):
    def setUp(self):
        self.ns = route_scope()

    def test_conversion_fetches_snapshot_with_correct_format_and_signed_request(self):
        token = self.ns['office_snapshots'].add(b'confirmed XLSX bytes', 'xlsx')
        requests = self.ns['requests']
        requests.post.return_value.json.return_value = {'endConvert': True, 'fileUrl': 'http://public/cache/pdf'}
        requests.get.return_value.content = pdf_bytes()
        self.ns['_convert_object_to_pdf_bytes']('legacy.xls', token)
        body = requests.post.call_args.kwargs['json']
        self.assertEqual(body['filetype'], 'xlsx')
        self.assertEqual(body['url'], f'http://backend/api/onlyoffice/snapshots/{token}')
        self.assertEqual(body['spreadsheetLayout'], {'ignorePrintArea': False})
        claims = jwt.decode(body['token'], self.ns['ONLYOFFICE_JWT_SECRET'], algorithms=['HS256'])
        self.assertEqual(claims['url'], body['url'])
        requests.get.assert_called_once_with('http://office/cache/pdf', timeout=60)
        self.ns['_read_object'].assert_not_called()

    def test_force_save_command_correlates_request_and_signs_it(self):
        self.ns['requests'].post.return_value.json.return_value = {'error': 0}
        self.assertEqual(self.ns['_office_force_save']('key', 'me-export:request'), 0)
        call = self.ns['requests'].post.call_args
        self.assertEqual(call.args[0], 'http://office/command')
        body = call.kwargs['json']
        claims = jwt.decode(body['token'], self.ns['ONLYOFFICE_JWT_SECRET'], algorithms=['HS256'])
        self.assertEqual(claims, {'c': 'forcesave', 'key': 'key', 'userdata': 'me-export:request'})

    def test_snapshot_endpoint_returns_only_frozen_bytes_and_expires(self):
        token = self.ns['office_snapshots'].add(b'frozen', 'xlsx')
        response = self.ns['onlyoffice_snapshot_download'](token)
        self.assertEqual(response.body, b'frozen')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.ns['office_snapshots'].remove(token)
        with self.assertRaises(HTTPException) as error:
            self.ns['onlyoffice_snapshot_download'](token)
        self.assertEqual(error.exception.status_code, 404)

    def test_merge_freezes_all_files_before_conversion_and_preserves_order(self):
        prepared = []
        def snapshot(name, etag, read, command):
            prepared.append(name)
            return name.encode(), 'xlsx'
        self.ns['office_sessions'].snapshot.side_effect = snapshot
        def convert(name, token):
            self.assertEqual(prepared, ['a.xlsx', 'b.xlsx'])
            self.assertEqual(self.ns['office_snapshots'].get(token)[0], name.encode())
            return pdf_bytes(600 if name == 'a.xlsx' else 700)
        self.ns['_convert_object_to_pdf_bytes'] = convert
        payload = SimpleNamespace(object_names=['a.xlsx', 'b.xlsx', 'a.xlsx'])
        data = self.ns['_combine_pdf_bytes'](payload)
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(io.BytesIO(data)).pages],
                         [600, 700, 600])
        self.assertEqual(self.ns['office_snapshots'].items, {})

    def test_failed_snapshot_aborts_report_and_cleans_prior_snapshots(self):
        self.ns['office_sessions'].snapshot.side_effect = [(b'first', 'xlsx'), RuntimeError('save timeout')]
        convert = Mock()
        self.ns['_convert_object_to_pdf_bytes'] = convert
        with self.assertRaises(HTTPException) as error:
            self.ns['_combine_pdf_bytes'](SimpleNamespace(object_names=['a.xlsx', 'b.xlsx']))
        self.assertIn('b.xlsx', error.exception.detail)
        self.assertEqual(self.ns['office_snapshots'].items, {})
        convert.assert_not_called()

    def test_failed_conversion_cleans_all_snapshots(self):
        self.ns['office_sessions'].snapshot.return_value = (b'data', 'xlsx')
        self.ns['_convert_object_to_pdf_bytes'] = Mock(side_effect=RuntimeError('conversion failed'))
        with self.assertRaises(RuntimeError):
            self.ns['_combine_pdf_bytes'](SimpleNamespace(object_names=['a.xlsx', 'b.xlsx']))
        self.assertEqual(self.ns['office_snapshots'].items, {})

    def test_pdf_snapshot_is_passed_through_without_conversion(self):
        data = pdf_bytes()
        token = self.ns['office_snapshots'].add(data, 'pdf')
        self.assertEqual(self.ns['_convert_object_to_pdf_bytes']('source.pdf', token), data)
        self.ns['requests'].post.assert_not_called()


class OfficeCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_payload_is_authoritative_for_body_and_header_tokens(self):
        for wrapped in (False, True):
            ns = route_scope()
            trusted = {'key': 'real-key', 'status': 6, 'url': 'http://office/real',
                       'userdata': 'me-export:real', 'filetype': 'xlsx'}
            token = jwt.encode({'payload': trusted} if wrapped else trusted,
                               ns['ONLYOFFICE_JWT_SECRET'], algorithm='HS256')
            request = SimpleNamespace(headers={'Authorization': f'Bearer {token}'},
                                      json=AsyncMock(return_value={'key': 'tampered', 'status': 2}))
            result = await ns['onlyoffice_callback']('a.xlsx', request)
            self.assertEqual(result, {'error': 0})
            ns['_save_onlyoffice_callback'].assert_called_once_with('a.xlsx', trusted)

    async def test_storage_failure_returns_nonzero_error(self):
        ns = route_scope()
        ns['ONLYOFFICE_JWT_SECRET'] = ''
        ns['_save_onlyoffice_callback'].side_effect = OSError('offline')
        request = SimpleNamespace(json=AsyncMock(return_value={'key': 'key', 'status': 2}))
        response = await ns['onlyoffice_callback']('a.xlsx', request)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.body), {'error': 1})

    async def test_invalid_jwt_cannot_write(self):
        ns = route_scope()
        request = SimpleNamespace(headers={}, json=AsyncMock(return_value={'token': 'bad'}))
        with self.assertRaises(HTTPException) as error:
            await ns['onlyoffice_callback']('a.xlsx', request)
        self.assertEqual(error.exception.status_code, 403)
        ns['_save_onlyoffice_callback'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
