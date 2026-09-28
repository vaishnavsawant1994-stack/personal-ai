from models.resilience import ModelObservability

def test_generation_allowlist_has_no_endpoint_url():
    assert 'endpoint' not in ModelObservability.SAFE_FIELDS and 'base_url' not in ModelObservability.SAFE_FIELDS
