from models.resilience import CircuitBreaker

def test_half_open_success_closes_circuit():
    b=CircuitBreaker(failure_threshold=1,recovery_seconds=1);b.failure(1);assert b.allow(2);b.success();assert b.state=='closed' and b.failures==0
