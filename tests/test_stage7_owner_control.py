from pathlib import Path


def test_owner_control_device_view_is_safe_live_presence_projection():
    source = Path('ui/control_panel.py').read_text(encoding='utf-8')
    assert "OWNER CONTROL CENTER" in source
    assert "Devices & Presence" in source
    assert "device_gateway'].online()" in source
    assert "'presence_state':'online'" in source
    assert "'trust_state':'trusted'" in source
    assert "self.views['Devices'].setPlainText(json.dumps(rt['device_registry'].list()" not in source


def test_owner_control_does_not_invent_stage7_privacy_authority():
    source = Path('ui/control_panel.py').read_text(encoding='utf-8')
    assert 'LOCAL_ONLY' not in source
    assert 'LOCAL_PREFERRED' not in source
    assert 'EXTERNAL_ALLOWED' not in source


def test_owner_control_projects_existing_model_and_preference_authorities():
    source = Path('ui/control_panel.py').read_text(encoding='utf-8')
    assert "'Models'" in source
    assert "models.health_status(probe=False)" in source
    assert "rt['preferences'].snapshot()" in source
    assert "'reduce_motion':prefs.get('reduce_motion')" in source
    assert "'autonomy_mode':prefs.get('autonomy_mode')" in source


def test_owner_control_privacy_view_is_truthful_and_non_authoritative():
    source = Path('ui/control_panel.py').read_text(encoding='utf-8')
    assert "'Privacy & Data'" in source
    assert "'sensitive_memory_remote_access':'scope-gated'" in source
    assert "'secret_store_exported_in_backups':False" in source
    assert "'device_presence':'live-evidence-only'" in source
    assert "'permission_default':'deny'" in source
    assert "'model_privacy_mode':prefs.get('model_privacy_mode','local_preferred')" in source
