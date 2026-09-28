from models.resilience import HealthState,ModelObservability


def test_configuration_is_not_health():
    obs=ModelObservability(['p']);obs.configured('p',True)
    status=obs.snapshot()['providers']['p']
    assert status['configuration']=='configured'
    assert status['state']==HealthState.UNKNOWN.value


def test_failure_and_recovery_timestamps_are_tracked():
    obs=ModelObservability(['p']);obs.configured('p',True);obs.failure('p','timeout',retryable=True,now=10);obs.success('p',5,now=20)
    status=obs.snapshot()['providers']['p']
    assert status['last_failure_at']==10 and status['last_success_at']==20 and status['recovered_at']==20
    assert status['consecutive_failures']==0


def test_history_is_bounded():
    obs=ModelObservability(['p'],history_limit=10)
    for i in range(30):obs.add_generation({'generation_id':f'gen_{i}','provider':'p','result':'success'})
    assert len(obs.snapshot()['recent_generations'])==10
