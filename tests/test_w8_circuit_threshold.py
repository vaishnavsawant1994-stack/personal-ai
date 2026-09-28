from models.resilience import CircuitBreaker

def test_circuit_threshold_is_bounded_default():assert CircuitBreaker().failure_threshold==3 and CircuitBreaker().recovery_seconds==30.0
