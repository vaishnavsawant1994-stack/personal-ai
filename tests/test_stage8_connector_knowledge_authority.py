import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from knowledge.governance import KnowledgeAuthority
from knowledge.store import KnowledgeStore
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.connector_api import connector_router


SENTINEL = 'STAGE8_CONNECTOR_KNOWLEDGE_AUTHORITY_SENTINEL'


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
            'filename': 'stage8-connector-authority.txt',
            'content': SENTINEL.encode(),
            'media_type': 'text/plain',
            'provenance': {
                'connector_id': 'drive',
                'provider': 'google',
                'provider_file_id': str(file_id),
                'version': '1',
                'modified_time': '2026-09-19T00:00:00Z',
                'checksum': 'fixture-checksum',
                'source_reference': 'https://drive.invalid/file-1',
            },
        }


def make_client(base, scopes, device_registry=None):
    store = KnowledgeStore(base / 'knowledge.sqlite3', base / 'objects')
    knowledge = KnowledgeAuthority(store)
    drive = Drive()
    runtime = {
        'device_registry': device_registry or Devices(scopes),
        'integrations': SimpleNamespace(list=lambda: []),
        'oauth': None,
        'oauth_providers': {},
        'integration_adapters': {'drive': drive},
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
    return client, knowledge, drive, store


def durable_counts(store):
    with sqlite3.connect(store.path) as con:
        return {
            'sources': con.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0],
            'source_documents': con.execute('SELECT COUNT(*) FROM knowledge_source_documents').fetchone()[0],
            'sync_requests': con.execute('SELECT COUNT(*) FROM knowledge_sync_requests').fetchone()[0],
            'documents': con.execute('SELECT COUNT(*) FROM knowledge_documents').fetchone()[0],
            'chunks': con.execute('SELECT COUNT(*) FROM knowledge_chunks').fetchone()[0],
        }


def test_stage8_connector_knowledge_requires_knowledge_write_not_device_admin(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'blocked',
        {'device:admin'},
    )

    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True},
    )

    assert response.status_code == 403
    assert 'knowledge:write' in response.json()['detail']
    assert drive.read_count == 0
    assert drive.events == []
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


def test_stage8_connector_knowledge_authorized_positive_control(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'allowed',
        {'device:admin', 'knowledge:write'},
    )

    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True},
    )

    assert response.status_code == 200
    document = response.json()
    assert drive.read_count == 1
    assert knowledge.detail(document['id']) is not None
    evidence = knowledge.source_evidence(document['id'])
    assert evidence and evidence[0]['source_type'] == 'google-drive'
    assert knowledge.search(SENTINEL)
    counts = durable_counts(store)
    assert counts['sources'] == 1
    assert counts['source_documents'] == 1
    assert counts['documents'] == 1
    assert counts['chunks'] >= 1
    assert [event for event, _ in drive.events] == [
        'knowledge.ingestion.requested',
        'knowledge.ingestion.completed',
    ]
    assert SENTINEL not in repr(drive.events)


def test_stage8_connector_private_knowledge_requires_private_capability(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'private-blocked',
        {'knowledge:write'},
    )

    response = client.post(
        '/iphone/api/connectors/drive/files/private-file/knowledge',
        json={'approved': True, 'access_class': 'private'},
    )

    assert response.status_code == 403
    assert 'knowledge:private' in response.json()['detail']
    assert drive.read_count == 0
    assert drive.events == []
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


def test_stage8_connector_private_knowledge_authorized_positive_control(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'private-allowed',
        {'knowledge:write', 'knowledge:private'},
    )

    response = client.post(
        '/iphone/api/connectors/drive/files/private-file/knowledge',
        json={'approved': True, 'access_class': 'private'},
    )

    assert response.status_code == 200
    document = response.json()
    assert document['access_class'] == 'private'
    assert drive.read_count == 1
    assert knowledge.detail(document['id'])['access_class'] == 'private'
    counts = durable_counts(store)
    assert counts['sources'] == 1
    assert counts['source_documents'] == 1
    assert counts['documents'] == 1
    assert counts['chunks'] >= 1


class AuthenticateOnlyDevices:
    def authenticate(self, device_id, token):
        return device_id == 'device-1' and token == 'token-1'


def test_stage8_connector_scope_authorization_fails_closed_when_unavailable(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'missing-scope-authorizer',
        {'knowledge:write'},
        device_registry=AuthenticateOnlyDevices(),
    )

    response = client.post(
        '/iphone/api/connectors/drive/files/file-1/knowledge',
        json={'approved': True},
    )

    assert response.status_code == 503
    assert 'scope authorization is unavailable' in response.json()['detail']
    assert drive.read_count == 0
    assert drive.events == []
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


def test_stage8_private_connector_ingest_cannot_reuse_less_restricted_checksum_duplicate(tmp_path):
    client, knowledge, drive, store = make_client(
        tmp_path / 'classification-dedupe',
        {'knowledge:write', 'knowledge:private'},
    )
    existing = knowledge.ingest(
        filename='existing-owner.txt',
        data=SENTINEL.encode(),
        source='owner-upload',
        access_class='owner',
    )
    assert existing['access_class'] == 'owner'

    response = client.post(
        '/iphone/api/connectors/drive/files/private-file/knowledge',
        json={'approved': True, 'access_class': 'private'},
    )

    assert response.status_code == 200
    document = response.json()
    assert document['id'] != existing['id']
    assert document['access_class'] == 'private'
    assert knowledge.detail(document['id'])['access_class'] == 'private'
    assert knowledge.search(SENTINEL, access_classes={'owner'})[0]['document_id'] == existing['id']
    private_hits = knowledge.search(SENTINEL, access_classes={'private'})
    assert private_hits and private_hits[0]['document_id'] == document['id']
