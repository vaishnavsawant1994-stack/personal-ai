from pathlib import Path
import inspect
import re

from security.policy_store import PolicyStore
from tools import desktop_file


PRODUCTION_FILES=(
    'desktop/file_operator.py',
    'desktop/input_clipboard.py',
    'desktop/platform_adapter.py',
    'desktop/safe_desktop_operator.py',
    'tools/desktop_file.py',
    'tools/builtins.py',
)


def source_text():
    return '\n'.join(Path(path).read_text(encoding='utf-8') for path in PRODUCTION_FILES)


def test_w75_reuses_schema_73_without_new_migration(tmp_path):
    store=PolicyStore(tmp_path/'policy.db')
    assert store.schema_version()==73


def test_w75_changed_production_surface_has_no_hardcoded_secret_patterns():
    text=source_text()
    forbidden=(r'\bsk-[A-Za-z0-9_-]{16,}\b',r'\bAKIA[0-9A-Z]{16}\b',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret)\s*=\s*["\'][^"\']{12,}["\']')
    assert not any(re.search(pattern,text) for pattern in forbidden)


def test_w75_has_no_shell_elevation_registry_service_or_monitoring_capability():
    text=source_text().lower()
    forbidden=('shell=true','cmd.exe','powershell','reg.exe','sc.exe','netsh','shutdown.exe','restart-computer','keyboard.hook','keylog','setinterval','create_remote_thread')
    assert not any(token in text for token in forbidden)


def test_w75_side_effect_tool_cannot_drop_below_external_side_effect_risk():
    source=inspect.getsource(desktop_file)
    assert 'Risk.EXTERNAL_SIDE_EFFECT' in source and 'requires_reauth=True' in source and 'requires_trusted_context=True' in source


def test_existing_owner_settings_surface_exposes_w75_policy_targets_and_recovery_audit():
    source=Path('ui/settings_panel.py').read_text(encoding='utf-8').lower()
    for token in ('application','path','clipboard','recent','revoke','reset'):
        assert token in source
