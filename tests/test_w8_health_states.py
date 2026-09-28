from models.resilience import HealthState,CircuitState


def test_required_health_states_are_stable():
    assert {x.value for x in HealthState}=={'unknown','healthy','degraded','unhealthy','unavailable','disabled'}


def test_required_circuit_states_are_stable():
    assert {x.value for x in CircuitState}=={'closed','open','half_open'}
