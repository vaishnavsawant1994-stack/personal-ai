from models.resilience import HealthRecord

def test_new_health_record_is_unknown():assert HealthRecord().state=='unknown'
