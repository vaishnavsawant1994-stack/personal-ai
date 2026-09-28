"""Stage-8: never_store fail-closed and Sheets Knowledge parity with Drive."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from knowledge.governance import KnowledgeAuthority
from knowledge.store import KnowledgeStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.connector_api import connector_router


SENTINEL = 'STAGE8_NEVER_STORE_SHEETS_SENTINEL'


class Devices:
    def __init__(self, scopes):
        self.scopes = set(scopes)

    def authenticate(self, device_id, token):
        return device_id == 'device-1' and token == 'token-1'

    def authorize(self, device_id, scope):
        return device_id == 'device-1' and scope in self.scopes


class TrustedContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = set_trusted_request(TrustedRequestContext('device-1', 'session-1'))
        try:
            return await call_next(request)
        finally:
            reset_trusted_request(token)


class Drive:
    def __init__(self):
        self.events = []
        self.read_count = 0

    def audit(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))

    def read_file(self, file_id, **ctx):
        self.read_count += 1
        return {
            'filename': 'stage8-drive.txt',
            'content': SENTINEL.encode(),
            'media_type': 'text/plain',
            'provenance': {
                'connector_id': 'drive',
                'provider': 'google',
                'provider_file_id': str(file_id),
                'version': '1',
                'modified_time': '2026-09-19T00:00:00Z',
                'checksum': 'fixture-drive-checksum',
                'source_reference': 'https://drive.invalid/file-1',
                'source_classification': 'owner',
            },
        }


class Sheets:
    def __init__(self):
        self.events = []
        self.read_count = 0

    def audit(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))

    def read_values(self, spreadsheet_id, a1_range, **ctx):
        self.read_count += 1
        return {
            'range': a1_range,
            'bounds': {'rows': 1, 'cols': 1},
            'retrieval_time': '2026-09-19T00:00:00Z',
            'values': [[SENTINEL]],
            'value_mode': ctx.get('value_mode') or 'formatted',
            'source_classification': 'owner',
        }


def durable_counts(store):
    with sqlite3.connect(store.path) as con:
        return {
            'sources': con.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0],
            'source_documents': con.execute('SELECT COUNT(*) FROM knowledge_source_documents').fetchone()[0],
            'sync_requests': con.execute('SELECT COUNT(*) FROM knowledge_sync_requests').fetchone()[0],
            'documents': con.execute('SELECT COUNT(*) FROM knowledge_documents').fetchone()[0],
            'chunks': con.execute('SELECT COUNT(*) FROM knowledge_chunks').fetchone()[0],
        }


def make_client(base, scopes):
    store = KnowledgeStore(base / 'knowledge.sqlite3', base / 'objects')
    knowledge = KnowledgeAuthority(store)
    drive = Drive()
    sheets = Sheets()
    runtime = {
        'device_registry': Devices(scopes),
        'integrations': SimpleNamespace(list=lambda: [
            {'id': 'drive', 'name': 'Drive'},
            {'id': 'sheets', 'name': 'Sheets'},
        ]),
        'oauth': None,
        'oauth_providers': {},
        'integration_adapters': {'drive': drive, 'sheets': sheets},
        'knowledge': knowledge,
        'executor': SimpleNamespace(
            approvals=SimpleNamespace(current_security_epoch=lambda: 0)
        ),
    }
    app = FastAPI()
    app.add_middleware(TrustedContextMiddleware)
    app.include_router(connector_router(runtime))
    client = TestClient(app)
    client.cookies.set('pa_device', 'device-1')
    client.cookies.set('pa_token', 'token-1')
    return client, knowledge, drive, sheets, store


def test_stage8_drive_never_store_fails_closed_no_durable_side_effects(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'never-store-drive',
        {'knowledge:write'},
    )
    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True, 'never_store': True},
    )
    assert response.status_code == 403
    assert 'NEVER_STORE' in response.json()['detail']
    assert drive.read_count == 0
    assert knowledge.sources() == []
    assert knowledge.list() == []
    assert knowledge.search(SENTINEL) == []
    assert durable_counts(store) == {
        'sources': 0,
        'source_documents': 0,
        'sync_requests': 0,
        'documents': 0,
        'chunks': 0,
    }
    assert list(store.object_dir.iterdir()) == []


def test_stage8_sheets_requires_knowledge_write_not_device_admin(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'sheets-scope',
        {'device:admin'},
    )
    response = client.post(
        '/iphone/api/connectors/sheets/ss-1/knowledge',
        json={'approved': True, 'range': 'A1:B2'},
    )
    assert response.status_code == 403
    assert 'knowledge:write' in response.json()['detail']
    assert sheets.read_count == 0
    assert durable_counts(store) == {
        'sources': 0,
        'source_documents': 0,
        'sync_requests': 0,
        'documents': 0,
        'chunks': 0,
    }


def test_stage8_sheets_requires_explicit_approval(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'sheets-approval',
        {'knowledge:write'},
    )
    response = client.post(
        '/iphone/api/connectors/sheets/ss-1/knowledge',
        json={'approved': False, 'range': 'A1:B2'},
    )
    assert response.status_code == 409
    assert sheets.read_count == 0
    assert durable_counts(store) == {
        'sources': 0,
        'source_documents': 0,
        'sync_requests': 0,
        'documents': 0,
        'chunks': 0,
    }


def test_stage8_sheets_private_requires_private_capability(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'sheets-private',
        {'knowledge:write'},
    )
    response = client.post(
        '/iphone/api/connectors/sheets/ss-1/knowledge',
        json={'approved': True, 'range': 'A1:B2', 'access_class': 'private'},
    )
    assert response.status_code == 403
    assert 'knowledge:private' in response.json()['detail']
    assert sheets.read_count == 0
    assert durable_counts(store) == {
        'sources': 0,
        'source_documents': 0,
        'sync_requests': 0,
        'documents': 0,
        'chunks': 0,
    }


def test_stage8_sheets_never_store_fails_closed(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'never-store-sheets',
        {'knowledge:write'},
    )
    response = client.post(
        '/iphone/api/connectors/sheets/ss-1/knowledge',
        json={'approved': True, 'range': 'A1:B2', 'never_store': True},
    )
    assert response.status_code == 403
    assert 'NEVER_STORE' in response.json()['detail']
    assert sheets.read_count == 0
    assert durable_counts(store) == {
        'sources': 0,
        'source_documents': 0,
        'sync_requests': 0,
        'documents': 0,
        'chunks': 0,
    }
    assert list(store.object_dir.iterdir()) == []


def test_stage8_sheets_authorized_positive_control(tmp_path):
    client, knowledge, drive, sheets, store = make_client(
        tmp_path / 'sheets-ok',
        {'knowledge:write'},
    )
    response = client.post(
        '/iphone/api/connectors/sheets/ss-1/knowledge',
        json={'approved': True, 'range': 'Sheet1!A1:B2'},
    )
    assert response.status_code == 200, response.text
    assert sheets.read_count == 1
    counts = durable_counts(store)
    assert counts['documents'] >= 1
    assert counts['chunks'] >= 1
    assert knowledge.search(SENTINEL)
    assert SENTINEL not in repr(sheets.events)
