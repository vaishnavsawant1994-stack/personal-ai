from pathlib import Path

from qualification.program import P3QualificationProgram


def complete_trial(program, session_id, stage, latency=100.0):
    gate = program.GATES[stage]
    metrics = {key: True for key in gate.required_metrics}
    metrics.update({key: False for key in gate.zero_failure_metrics})
    program.record_trial(session_id, 'qualification-task', passed=True, latency_ms=latency, metrics=metrics, evidence={'source': 'test'})


def test_simulated_evidence_cannot_satisfy_real_device_gate(tmp_path: Path):
    program = P3QualificationProgram(tmp_path / 'p3.sqlite3')
    for _ in range(3):
        sid = program.start_session('P3.2', evidence_class='simulated')
        for _ in range(30):
            complete_trial(program, sid, 'P3.2')
        program.finish_session(sid, duration_seconds=60)
    result = program.evaluate('P3.2')
    assert result['passed'] is False
    assert result['sessions'] == 0
    assert 'real_device' in result['failures'][0]


def test_p3_3_zero_failure_invariant_is_fail_closed(tmp_path: Path):
    program = P3QualificationProgram(tmp_path / 'p3.sqlite3')
    for session_index in range(3):
        sid = program.start_session('P3.3', evidence_class='real_device', environment={'device': session_index})
        for trial_index in range(20):
            metrics = {key: True for key in program.GATES['P3.3'].required_metrics}
            metrics.update({key: False for key in program.GATES['P3.3'].zero_failure_metrics})
            if session_index == 0 and trial_index == 0:
                metrics['authority_bypass'] = True
            program.record_trial(sid, 'permission-boundary', passed=True, metrics=metrics)
        program.finish_session(sid, duration_seconds=30)
    result = program.evaluate('P3.3')
    assert result['passed'] is False
    assert any('authority_bypass' in failure for failure in result['failures'])


def test_p3_7_requires_soak_duration_not_just_success_count(tmp_path: Path):
    program = P3QualificationProgram(tmp_path / 'p3.sqlite3')
    for _ in range(3):
        sid = program.start_session('P3.7', evidence_class='production_like')
        for _ in range(70):
            complete_trial(program, sid, 'P3.7', latency=1000)
        program.finish_session(sid, duration_seconds=60)
    result = program.evaluate('P3.7')
    assert result['trials'] >= 200
    assert result['passed'] is False
    assert any('duration' in failure for failure in result['failures'])


def test_p3_8_cannot_pass_before_prerequisites(tmp_path: Path):
    program = P3QualificationProgram(tmp_path / 'p3.sqlite3')
    for _ in range(3):
        sid = program.start_session('P3.8', evidence_class='competitive')
        for _ in range(10):
            complete_trial(program, sid, 'P3.8')
        program.finish_session(sid, duration_seconds=60)
    result = program.evaluate('P3.8')
    assert result['passed'] is False
    assert any('prerequisites' in failure for failure in result['failures'])


def test_environment_and_evidence_are_retained(tmp_path: Path):
    program = P3QualificationProgram(tmp_path / 'p3.sqlite3')
    sid = program.start_session('P3.6', evidence_class='real_device', environment={'source': 'iphone', 'target': 'desktop'})
    program.record_trial(sid, 'handoff', passed=True, latency_ms=420, metrics={'handoff_preserved_context': True}, evidence={'thread': 'abc'})
    program.finish_session(sid, duration_seconds=5)
    session = program.session(sid)
    assert session['environment']['source'] == 'iphone'
    assert session['trials'][0]['evidence']['thread'] == 'abc'
