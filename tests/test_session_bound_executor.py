from __future__ import annotations

import pytest

from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.session_bound_executor import SessionBoundExecutor


class Executor:
    def __init__(self):
        self.calls = []

    def chat(self, text, **kwargs):
        self.calls.append(('chat', text, kwargs))
        return 'reply'

    def approve(self, approval_id, **kwargs):
        self.calls.append(('approve', approval_id, kwargs))
        return 'approved'

    def reject(self, approval_id, **kwargs):
        self.calls.append(('reject', approval_id, kwargs))
        return 'rejected'


def test_session_bound_executor_forwards_session_and_reauth():
    raw = Executor()
    bound = SessionBoundExecutor(raw)
    token = set_trusted_request(TrustedRequestContext('device-1', 'session-1', 123.0))
    try:
        assert bound.chat('hello', device_id='device-1') == 'reply'
        assert bound.approve('approval-1') == 'approved'
        assert bound.reject('approval-2') == 'rejected'
    finally:
        reset_trusted_request(token)

    assert raw.calls[0][2]['session_id'] == 'session-1'
    assert raw.calls[0][2]['reauthenticated_at'] == 123.0
    assert raw.calls[1][2]['session_id'] == 'session-1'
    assert raw.calls[1][2]['reauthenticated_at'] == 123.0
    assert raw.calls[2][2]['session_id'] == 'session-1'


def test_session_bound_executor_rejects_missing_or_mismatched_context():
    bound = SessionBoundExecutor(Executor())
    with pytest.raises(PermissionError, match='session'):
        bound.chat('hello')

    token = set_trusted_request(TrustedRequestContext('device-1', 'session-1', None))
    try:
        with pytest.raises(PermissionError, match='device mismatch'):
            bound.chat('hello', device_id='device-2')
    finally:
        reset_trusted_request(token)
