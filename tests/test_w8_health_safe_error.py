from models.resilience import ModelObservability

def test_health_record_has_error_code_not_error_message():
    row=ModelObservability(['p']).snapshot()['providers']['p'];assert 'last_error_code' in row and 'error_message' not in row
