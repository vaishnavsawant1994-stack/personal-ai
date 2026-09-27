from pathlib import Path

from core.events import EventBus
from qualification.voice import VoiceQualificationRecorder


def test_simulated_voice_session_records_latency_and_barge(tmp_path: Path):
    events = EventBus()
    recorder = VoiceQualificationRecorder(tmp_path / 'qualification.sqlite3', events=events)
    session_id = recorder.start_session(
        evidence_class='simulated',
        environment={'microphone': 'synthetic', 'speaker': 'synthetic', 'provider': 'fake'},
    )

    events.emit('voice.transcript', text='hello')
    events.emit('voice.reply', text='hi')
    events.emit('voice.barge_in')
    events.emit('voice.turn.cancelled')
    events.emit('state', state='listening')

    summary = recorder.stop_session()
    assert summary['session_id'] == session_id
    assert summary['turns'] == 1
    assert summary['barge_trials'] == 1
    assert summary['barge_successes'] == 1
    assert summary['barge_success_rate'] == 1.0
    assert summary['p95_transcript_to_reply_ms'] is not None
    assert summary['p95_barge_to_listening_ms'] is not None
    assert summary['errors'] == 0
    assert summary['passed'] is True


def test_real_device_session_cannot_pass_without_required_sample_size(tmp_path: Path):
    events = EventBus()
    recorder = VoiceQualificationRecorder(tmp_path / 'qualification.sqlite3', events=events)
    recorder.start_session(evidence_class='real_device', environment={'device': 'test rig'})
    events.emit('voice.transcript', text='one turn')
    events.emit('voice.reply', text='reply')
    summary = recorder.stop_session()

    assert summary['passed'] is False
    assert 'real_device_turns<30' in summary['failed_gates']
    assert 'barge_trials<10' in summary['failed_gates']


def test_voice_errors_are_retained_and_fail_qualification(tmp_path: Path):
    events = EventBus()
    recorder = VoiceQualificationRecorder(tmp_path / 'qualification.sqlite3', events=events)
    recorder.start_session(evidence_class='simulated')
    events.emit('voice.transcript', text='test')
    events.emit('voice.error', error='microphone disconnected')
    summary = recorder.stop_session()

    assert summary['errors'] == 1
    assert summary['passed'] is False
    assert 'voice_errors>0' in summary['failed_gates']


def test_sessions_preserve_environment_metadata(tmp_path: Path):
    recorder = VoiceQualificationRecorder(tmp_path / 'qualification.sqlite3')
    session_id = recorder.start_session(
        evidence_class='real_device',
        environment={'os': 'Windows 11', 'room': 'office', 'noise': 'moderate'},
        notes='physical microphone trial',
    )
    recorder.stop_session()
    row = recorder.sessions()[0]

    assert row['id'] == session_id
    assert row['environment']['os'] == 'Windows 11'
    assert row['environment']['noise'] == 'moderate'
