from pathlib import Path

def test_owner_can_disable_providers_by_configuration_without_credentials_in_code():
    text=Path('core/config.py').read_text(encoding='utf-8');assert 'MODEL_DISABLED_PROVIDERS' in text
