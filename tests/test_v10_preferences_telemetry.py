import json,time
from core.preferences import Preferences
from core.telemetry import Telemetry

def test_preferences_persist_and_reject_unknown(tmp_path):
    path=tmp_path/'prefs.json';p=Preferences(path);p.update(preferred_name='Vaishnav',reduce_motion=True,onboarding_complete=True)
    p2=Preferences(path);assert p2.get('preferred_name')=='Vaishnav';assert p2.get('reduce_motion') is True;assert p2.get('onboarding_complete') is True
    try:p2.set('unknown',True);assert False
    except KeyError:pass

def test_corrupt_preferences_fall_back_to_safe_defaults(tmp_path):
    path=tmp_path/'prefs.json';path.write_text('{broken');p=Preferences(path);assert p.get('autonomy_mode')=='ask';assert p.get('onboarding_complete') is False

def test_telemetry_is_local_and_reports_distribution(tmp_path):
    path=tmp_path/'telemetry.json';t=Telemetry(path);t.observe('latency',10);t.observe('latency',20);t.increment('errors');snap=t.persist();assert snap['metrics']['latency']['count']==2;assert snap['counters']['errors']==1
    on_disk=json.loads(path.read_text());assert on_disk['metrics']['latency']['max']==20.0

def test_telemetry_timer_records_milliseconds(tmp_path):
    t=Telemetry(tmp_path/'t.json')
    with t.timed('work'):time.sleep(.001)
    assert t.snapshot()['metrics']['work']['count']==1
