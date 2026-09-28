from models.governed_router import NON_RETRYABLE

def test_malformed_response_is_non_retryable():assert 'malformed_response' in NON_RETRYABLE
