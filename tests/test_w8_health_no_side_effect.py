from pathlib import Path

def test_health_probe_is_get_only():
    health=Path('models/governed_router.py').read_text(encoding='utf-8').split('def health_status',1)[1];assert "'GET','/models'" in health and "'POST'" not in health
