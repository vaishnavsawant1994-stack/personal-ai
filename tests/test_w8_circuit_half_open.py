from models.resilience import CircuitBreaker

def test_half_open_is_single_flight():
    b=CircuitBreaker(failure_threshold=1,recovery_seconds=1);b.failure(1);assert b.allow(2) is True and b.allow(2) is False
