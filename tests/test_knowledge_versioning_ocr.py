from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from knowledge.store import KnowledgeError, KnowledgeOcrUnavailable, KnowledgeStore


class FakeLocalOcr:
    external = False
    name = 'fake-local'

    def extract(self, data: bytes, *, filename: str, access_class: str):
        return [
            {'text': 'Invoice number 42', 'bbox': [10, 20, 120, 60], 'page': 1},
            {'text': f'Access class {access_class}', 'bbox': [10, 70, 180, 100], 'page': 1},
        ]


class FakeExternalOcr(FakeLocalOcr):
    external = True
    name = 'fake-external'


def store(tmp_path, **kwargs):
    return KnowledgeStore(tmp_path / 'knowledge.sqlite3', tmp_path / 'objects', **kwargs)


def pdf_bytes():
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(72, 720, 'PageOneUnique knowledge provenance')
    pdf.showPage()
    pdf.drawString(72, 720, 'PageTwoUnique knowledge provenance')
    pdf.save()
    return output.getvalue()


def image_bytes(size=(120, 80), fmt='PNG'):
    image = Image.new('RGB', size, 'white')
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def test_changed_document_creates_immutable_version_lineage_and_current_search(tmp_path):
    knowledge = store(tmp_path)
    v1 = knowledge.ingest(filename='policy.txt', data=b'Version one unique policy text', source='owner-upload', access_class='owner')
    v2 = knowledge.ingest(filename='policy.txt', data=b'Version two current policy text', source='owner-upload', access_class='owner')

    assert v1['lineage_id'] == v2['lineage_id']
    assert v1['version'] == 1
    assert v2['version'] == 2
    assert v2['current'] is True
    history = knowledge.history(v2['id'])
    assert [item['version'] for item in history] == [2, 1]
    assert [item['current'] for item in history] == [True, False]

    current_hits = knowledge.search('Version one unique')
    assert all(hit['version'] == 2 for hit in current_hits)
    assert all(hit['document_id'] != v1['id'] for hit in current_hits)
    historical = knowledge.search('Version one unique', include_history=True)
    version_one = next(hit for hit in historical if hit['document_id'] == v1['id'])
    assert version_one['version'] == 1
    assert version_one['citation']['lineage_id'] == v2['lineage_id']

    restarted = store(tmp_path)
    history_after_restart = restarted.history(v2['lineage_id'])
    assert [item['version'] for item in history_after_restart] == [2, 1]


def test_pdf_citations_include_version_page_and_chunk(tmp_path):
    knowledge = store(tmp_path)
    document = knowledge.ingest(filename='report.pdf', data=pdf_bytes(), source='board-report', access_class='owner')

    hits = knowledge.search('PageTwoUnique')
    assert hits
    citation = hits[0]['citation']
    assert citation['document_id'] == document['id']
    assert citation['lineage_id'] == document['lineage_id']
    assert citation['version'] == 1
    assert citation['source'] == 'board-report'
    assert citation['page_start'] == 2
    assert citation['page_end'] == 2
    assert isinstance(citation['chunk'], int)


def test_delete_one_version_repairs_lineage_and_delete_lineage_removes_all(tmp_path):
    knowledge = store(tmp_path)
    v1 = knowledge.ingest(filename='notes.txt', data=b'first version', source='same')
    v2 = knowledge.ingest(filename='notes.txt', data=b'second version', source='same')
    v3 = knowledge.ingest(filename='notes.txt', data=b'third version', source='same')

    assert knowledge.delete_version(v2['id']) is True
    history = knowledge.history(v3['lineage_id'])
    assert [item['version'] for item in history] == [3, 1]
    assert knowledge.detail(v1['id'])['superseded_by_id'] == v3['id']

    assert knowledge.delete_version(v3['id']) is True
    promoted = knowledge.detail(v1['id'])
    assert promoted['current'] is True
    assert promoted['superseded_by_id'] is None

    assert knowledge.delete_lineage(v1['lineage_id']) == 1
    assert knowledge.history(v1['lineage_id']) == []


def test_image_ingestion_is_bounded_sanitized_and_keeps_ocr_coordinates(tmp_path):
    knowledge = store(tmp_path, ocr_provider=FakeLocalOcr())
    document = knowledge.ingest(filename='invoice.png', data=image_bytes(), source='owner-image', access_class='private')
    assert document['metadata']['metadata_stripped'] is True
    assert document['metadata']['stored_format'] == 'png'
    hit = knowledge.search('Invoice number 42', access_classes={'private'})[0]
    assert hit['citation']['page_start'] == 1
    assert hit['citation']['location']['bbox'] == [10, 20, 120, 60]


def test_ocr_unavailable_and_private_external_ocr_fail_closed(tmp_path):
    knowledge = store(tmp_path)
    with pytest.raises(KnowledgeOcrUnavailable, match='OCR unavailable'):
        knowledge.ingest(filename='image.png', data=image_bytes(), access_class='owner')

    external = store(tmp_path / 'external', ocr_provider=FakeExternalOcr())
    with pytest.raises(KnowledgeOcrUnavailable, match='private images'):
        external.ingest(filename='private.png', data=image_bytes(), access_class='private')


def test_malformed_and_oversized_pixel_images_are_rejected_deterministically(tmp_path):
    knowledge = store(tmp_path, ocr_provider=FakeLocalOcr())
    with pytest.raises(KnowledgeError, match='malformed'):
        knowledge.ingest(filename='broken.png', data=b'not-an-image', access_class='owner')

    knowledge.MAX_IMAGE_PIXELS = 100
    with pytest.raises(KnowledgeError, match='pixel count'):
        knowledge.ingest(filename='large.png', data=image_bytes((11, 11)), access_class='owner')


def test_reverting_to_historical_checksum_is_valid_and_restart_safe(tmp_path):
    knowledge = store(tmp_path)
    v1 = knowledge.ingest(filename='policy.txt', data=b'alpha version', source='owner-upload')
    knowledge.ingest(filename='policy.txt', data=b'beta version', source='owner-upload')
    v3 = knowledge.ingest(filename='policy.txt', data=b'alpha version', source='owner-upload')
    assert v3['version'] == 3
    assert v3['checksum'] == v1['checksum']
    restarted = store(tmp_path)
    history = restarted.history(v3['lineage_id'])
    assert [item['version'] for item in history] == [3, 2, 1]


def test_office_archive_expansion_and_paths_are_bounded(tmp_path):
    knowledge = store(tmp_path)
    original_member_limit = KnowledgeStore.MAX_ARCHIVE_MEMBER_BYTES
    KnowledgeStore.MAX_ARCHIVE_MEMBER_BYTES = 1024
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', 'x' * 2048)
    with pytest.raises(KnowledgeError, match='member exceeds'):
        knowledge.ingest(filename='oversized.docx', data=output.getvalue())

    KnowledgeStore.MAX_ARCHIVE_MEMBER_BYTES = original_member_limit

    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('../escape.xml', '<x/>')
    with pytest.raises(KnowledgeError, match='unsafe path'):
        knowledge.ingest(filename='unsafe.docx', data=traversal.getvalue())
