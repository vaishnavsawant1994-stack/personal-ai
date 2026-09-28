from models.resilience import CircuitState

def test_circuit_state_names_match_w8_contract():assert [s.name for s in CircuitState]==['CLOSED','OPEN','HALF_OPEN']
