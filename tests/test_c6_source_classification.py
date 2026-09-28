"""A caller cannot store a connector source below its classification."""

from __future__ import annotations

import pytest

from integrations.knowledge_bridge import ConnectorKnowledgeIngestor
from knowledge.classification import enforce_source_minimum
from knowledge.store import KnowledgeError, KnowledgeStore


class Memory:
    def __init__(self):
        self.calls = []

    def ingest(self, **kwargs):
        self.calls.append(kwargs)
        return {'id': 'doc-1', 'version': 1}


class Drive:
    def __init__(self, item):
        self.item = item
        self.events = []

    def audit(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))

    def read_file(self, file_id, **ctx):
        return self.item


def test_private_source_cannot_be_requested_as_owner_or_public():
    with pytest.raises(ValueError):
        enforce_source_minimum('owner', 'private')
    with pytest.raises(ValueError):
        enforce_source_minimum('public', 'private')
    assert enforce_source_minimum('private', 'private') == 'private'
    assert enforce_source_minimum('private', 'owner') == 'private'


def test_connector_downgrade_does_not_write(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    memory = Memory()
    drive = Drive({
        'filename': 'secret.txt',
        'content': b'secret connector body',
        'media_type': 'text/plain',
        'provenance': {'connector_id': 'drive', 'source_classification': 'private'},
    })
    with pytest.raises(PermissionError):
        ConnectorKnowledgeIngestor(memory).ingest_drive(
            drive, 'file-1', approved=True, owner_id='owner', device_id='device', session_id='session', access_class='owner',
        )
    assert memory.calls == []
    assert knowledge.list() == []


def test_missing_connector_classification_stays_private(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    with pytest.raises(KnowledgeError):
        knowledge.ingest(
            filename='note.txt',
            data=b'connector text that must not become owner',
            source='google-drive:file-1',
            access_class='owner',
        )
    assert knowledge.list() == []
    document = knowledge.ingest(
        filename='note.txt',
        data=b'connector text that must not become owner',
        source='google-drive:file-1',
        access_class='private',
        metadata={'source_minimum_classification': 'private'},
    )
    assert document['access_class'] == 'private'
    assert document['metadata']['source_minimum_classification'] == 'private'
    with pytest.raises(KnowledgeError):
        knowledge.update(document['id'], access_class='owner')
    with pytest.raises(KnowledgeError):
        knowledge.update(document['id'], metadata={'source_minimum_classification': 'owner'})
    assert knowledge.detail(document['id'])['access_class'] == 'private'


def test_owner_upload_without_a_connector_source_is_unchanged(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    document = knowledge.ingest(
        filename='mine.txt',
        data=b'owner written note',
        source='owner-upload',
        access_class='owner',
        metadata={'source_minimum_classification': 'owner', 'note': 'kept'},
    )
    assert document['access_class'] == 'owner'
    assert document['metadata'].get('note') == 'kept'
    assert 'source_minimum_classification' not in document['metadata']


def test_caller_metadata_cannot_lower_a_connector_floor(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    with pytest.raises(KnowledgeError):
        knowledge.ingest(
            filename='note.txt',
            data=b'forged floor',
            source='google-drive:file-1',
            access_class='owner',
            metadata={'source_minimum_classification': 'owner'},
        )
    assert knowledge.list() == []
    with pytest.raises(KnowledgeError):
        knowledge.ingest(
            filename='mail.txt',
            data=b'forged connector floor',
            source='connector:mail:1',
            access_class='owner',
            metadata={'source_minimum_classification': 'public'},
        )
    assert knowledge.list() == []


def test_read_classification_is_the_minimum_and_stronger_is_allowed(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    owner_doc = knowledge.ingest(
        filename='owned.txt',
        data=b'classified by the read',
        source='google-drive:file-1',
        access_class='owner',
        source_minimum='owner',
    )
    assert owner_doc['access_class'] == 'owner'
    assert owner_doc['metadata']['source_minimum_classification'] == 'owner'
    assert owner_doc['metadata']['effective_access_class'] == 'owner'
    private_doc = knowledge.ingest(
        filename='stronger.txt',
        data=b'stored above the read',
        source='google-drive:file-2',
        access_class='private',
        source_minimum='owner',
    )
    assert private_doc['access_class'] == 'private'
    assert private_doc['metadata']['source_minimum_classification'] == 'owner'
    assert private_doc['metadata']['effective_access_class'] == 'private'


def test_secret_and_never_store_classifications_are_not_weakened_into_knowledge(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    for minimum in ('secret', 'never_store'):
        with pytest.raises(KnowledgeError):
            knowledge.ingest(
                filename='hidden.txt',
                data=b'must not be stored',
                source='google-drive:file-1',
                access_class='private',
                source_minimum=minimum,
            )
    assert knowledge.list() == []


def test_later_version_cannot_drop_the_recorded_floor(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    first = knowledge.ingest(
        filename='note.txt',
        data=b'first version',
        source='google-drive:file-1',
        access_class='private',
        source_minimum='private',
    )
    with pytest.raises(KnowledgeError):
        knowledge.ingest(
            filename='note.txt',
            data=b'second version forged lower',
            source='google-drive:file-1',
            access_class='owner',
            source_minimum='owner',
        )
    current = knowledge.detail(first['id'])
    assert current['current'] is True
    assert current['access_class'] == 'private'
    assert [item['id'] for item in knowledge.list()] == [first['id']]


def test_update_cannot_relabel_an_owner_document_as_a_connector_source(tmp_path):
    knowledge = KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects')
    document = knowledge.ingest(filename='mine.txt', data=b'owner written note', source='owner-upload', access_class='owner')
    with pytest.raises(KnowledgeError):
        knowledge.update(document['id'], source='google-drive:file-1')
    saved = knowledge.detail(document['id'])
    assert saved['source'] == 'owner-upload'
    assert saved['access_class'] == 'owner'


def test_missing_connector_read_does_not_write_and_private_records_the_floor():
    memory = Memory()
    drive = Drive({
        'filename': 'unclassified.txt',
        'content': b'no classification on the read',
        'media_type': 'text/plain',
        'provenance': {'connector_id': 'drive'},
    })
    bridge = ConnectorKnowledgeIngestor(memory)
    with pytest.raises(PermissionError):
        bridge.ingest_drive(drive, 'file-1', approved=True, owner_id='owner', device_id='device', session_id='session', access_class='owner')
    assert memory.calls == []
    bridge.ingest_drive(drive, 'file-1', approved=True, owner_id='owner', device_id='device', session_id='session', access_class='private')
    assert memory.calls[0]['access_class'] == 'private'
    assert memory.calls[0]['source_minimum'] == 'private'
    assert memory.calls[0]['metadata']['source_minimum_classification'] == 'private'
    assert memory.calls[0]['metadata']['effective_access_class'] == 'private'


def test_connector_secret_classification_does_not_write():
    memory = Memory()
    drive = Drive({
        'filename': 'secret.txt',
        'content': b'secret body',
        'media_type': 'text/plain',
        'provenance': {'source_classification': 'secret'},
    })
    with pytest.raises(PermissionError):
        ConnectorKnowledgeIngestor(memory).ingest_drive(
            drive, 'file-1', approved=True, owner_id='owner', device_id='device', session_id='session', access_class='private',
        )
    assert memory.calls == []

