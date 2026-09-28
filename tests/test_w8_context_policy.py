from models.governed_router import NON_RETRYABLE


def test_context_limit_requires_explicit_strategy_not_blind_retry():
    assert 'context_limit' in NON_RETRYABLE
