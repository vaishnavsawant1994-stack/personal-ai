from models.resilience import ModelObservability


def test_circuit_transition_metric_changes_only_on_state_transition():
    obs=ModelObservability(['p']);obs.breakers['p'].failure_threshold=2
    obs.failure('p','timeout',retryable=True,now=1);assert obs.snapshot()['counters']['circuit_transitions']==0
    obs.failure('p','timeout',retryable=True,now=2);assert obs.snapshot()['counters']['circuit_transitions']==1
    obs.failure('p','timeout',retryable=True,now=3);assert obs.snapshot()['counters']['circuit_transitions']==1
