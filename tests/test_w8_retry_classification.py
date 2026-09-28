from models.governed_router import NON_RETRYABLE


def test_non_retryable_error_classes_are_explicit():
    required={'authentication_error','configuration_error','unsupported_capability','invalid_request','context_limit','policy_denied','malformed_response','cancelled_request'}
    assert required.issubset(NON_RETRYABLE)
