from models.resilience import HealthState

def test_health_state_names_match_w8_contract():assert [s.name for s in HealthState]==['UNKNOWN','HEALTHY','DEGRADED','UNHEALTHY','UNAVAILABLE','DISABLED']
