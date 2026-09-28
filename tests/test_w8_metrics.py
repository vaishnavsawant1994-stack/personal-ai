from models.resilience import ModelObservability


def test_metrics_include_required_aggregate_counters():
    counters=ModelObservability(['p']).snapshot()['counters']
    for key in ('requests','successes','failures','timeouts','retries','failovers','rate_limits','malformed','capability_mismatch','policy_blocked','circuit_transitions'):
        assert key in counters
