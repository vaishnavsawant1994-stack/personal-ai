import hashlib
import io
import time

import pytest
from PIL import Image

from desktop.evidence_geometry import COORDINATE_SPACE_VERSION
from vision.screen_understanding import EvidenceGuardError, SanitizedEvidenceGuard

# W7.2 exact-head qualification: guard fixtures follow the live provenance version.

def _record():
    buffer = io.BytesIO(); Image.new('RGB', (3, 3), 'black').save(buffer, format='PNG'); raw = buffer.getvalue()
    return {'redaction_status':'sanitized','visual_evidence_unavailable':False,'coordinate_space_version':COORDINATE_SPACE_VERSION,'expires_at':time.time()+60,'owner_id':'owner','device_id':'device','session_id':'session','_sanitized_png':raw,'sanitized_checksum':hashlib.sha256(raw).hexdigest()}


def test_guard_accepts_bound_sanitized_evidence():
    assert SanitizedEvidenceGuard.consume(_record(), owner_id='owner', device_id='device', session_id='session').startswith('data:image/png;base64,')


def test_guard_rejects_wrong_binding_checksum_and_expiry():
    with pytest.raises(EvidenceGuardError): SanitizedEvidenceGuard.consume(_record(), owner_id='other')
    bad = _record(); bad['sanitized_checksum'] = 'bad'
    with pytest.raises(EvidenceGuardError): SanitizedEvidenceGuard.consume(bad)
    expired = _record(); expired['expires_at'] = time.time()-1
    with pytest.raises(EvidenceGuardError): SanitizedEvidenceGuard.consume(expired)


def test_guard_rejects_unavailable_or_unknown_provenance():
    unavailable = _record(); unavailable['visual_evidence_unavailable'] = True
    with pytest.raises(EvidenceGuardError): SanitizedEvidenceGuard.consume(unavailable)
    unknown = _record(); unknown['coordinate_space_version'] = COORDINATE_SPACE_VERSION + 999
    with pytest.raises(EvidenceGuardError): SanitizedEvidenceGuard.consume(unknown)
