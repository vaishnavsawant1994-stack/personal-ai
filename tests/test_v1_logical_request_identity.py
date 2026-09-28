from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.logical_request import LogicalTurnBody, validate_request_id


def test_request_id_accepts_canonical_client_uuid_and_normalizes_case():
    request_id = "550E8400-E29B-41D4-A716-446655440000"
    body = LogicalTurnBody(request_id=request_id, transcript="hello")
    assert body.request_id == request_id.lower()


@pytest.mark.parametrize("value", ["", "r1", "../request", "x" * 65, "550e8400-e29b-01d4-a716-446655440000"])
def test_request_id_rejects_missing_unbounded_or_unsafe_values(value):
    with pytest.raises((ValueError, ValidationError)):
        LogicalTurnBody(request_id=value, transcript="hello")


def test_request_id_is_identity_metadata_not_authority():
    assert validate_request_id("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"
    fields = set(LogicalTurnBody.model_fields)
    assert fields == {"request_id", "transcript", "conversation_id"}
    assert not ({"owner_id", "device_id", "session_id", "security_epoch"} & fields)
