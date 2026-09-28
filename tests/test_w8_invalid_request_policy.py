from models.governed_router import NON_RETRYABLE


def test_invalid_request_and_policy_denial_are_not_retryable():
    assert {'invalid_request','policy_denied'}.issubset(NON_RETRYABLE)
