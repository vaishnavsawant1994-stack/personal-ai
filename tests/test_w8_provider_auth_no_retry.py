from models.governed_router import NON_RETRYABLE

def test_authentication_failure_is_non_retryable():assert 'authentication_error' in NON_RETRYABLE
