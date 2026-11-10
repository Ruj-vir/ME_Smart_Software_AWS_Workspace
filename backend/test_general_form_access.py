"""Exercise page access without connecting to the database or object storage."""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool


class GeneralFormAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse(Path(__file__).with_name('server.py').read_text(encoding='utf-8'))
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'GENERAL_FORM_PAGES' for t in node.targets
            ):
                nodes.append(node)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == 'protect_general_form':
                node.decorator_list = []
                nodes.append(node)
        self.ns = dict(os=os, Request=Request, Response=Response,
                       RedirectResponse=RedirectResponse, HTTPException=HTTPException,
                       run_in_threadpool=run_in_threadpool)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'server.py', 'exec'), self.ns)

    async def check_access(self, role, query, expected):
        def current_user(request):
            if role is None:
                raise HTTPException(401)
            return {'role': role}
        self.ns['current_user'] = current_user
        for page in self.ns['GENERAL_FORM_PAGES']:
            with self.subTest(role=role, query=query, page=page):
                request = Request({'type': 'http', 'method': 'GET',
                                   'path': '/ui/' + page, 'query_string': query.encode(),
                                   'headers': []})
                next_handler = AsyncMock(return_value=Response('page'))
                response = await self.ns['protect_general_form'](request, next_handler)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(next_handler.await_count, int(expected == 200))

    async def test_user_can_select_forms(self):
        await self.check_access('user', 'mode=select', 200)
        await self.check_access('user', 'mode=select&report=Other', 200)

    async def test_user_cannot_open_management(self):
        for query in ('', 'mode=edit', 'mode=SELECT', 'mode=select&mode=edit',
                      'mode=edit&mode=select'):
            await self.check_access('user', query, 403)

    async def test_selection_requires_login(self):
        await self.check_access(None, 'mode=select', 303)
        await self.check_access(None, '', 303)

    async def test_admin_can_open_both_modes(self):
        await self.check_access('admin', '', 200)
        await self.check_access('admin', 'mode=select', 200)


if __name__ == '__main__':
    unittest.main()
