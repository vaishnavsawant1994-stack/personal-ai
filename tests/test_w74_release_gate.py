import inspect

from browser.safe_operator import SafeBrowserOperator, STRONG_OWNER_ACTIONS
from security.policy_store import PolicyStore


def test_w74_keeps_schema_73_and_reuses_w73_policy_authority(tmp_path):
    store = PolicyStore(tmp_path / 'policy.db')
    assert store.schema_version() == 73


def test_w74_browser_operator_has_no_cookie_storage_or_background_monitoring_surface():
    source = inspect.getsource(SafeBrowserOperator).lower()
    assert 'cookies(' not in source
    assert 'local_storage' not in source
    assert 'session_storage' not in source
    assert 'threading' not in source
    assert 'setinterval' not in source


def test_w74_strong_owner_side_effects_remain_explicitly_gated():
    required = {
        'email_send', 'message_send', 'purchase', 'financial_transfer',
        'public_publish', 'share', 'delete', 'destructive_delete',
        'security_setting_modify', 'permission_change', 'legal_acceptance',
    }
    assert required.issubset(STRONG_OWNER_ACTIONS)
