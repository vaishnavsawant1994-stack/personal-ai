from models.governed_router import NON_RETRYABLE


def test_cancelled_requests_are_never_retryable():
    assert 'cancelled_request' in NON_RETRYABLE
