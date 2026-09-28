from pathlib import Path

def test_disabled_provider_filter_precedes_health_route():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').split('def _eligible',1)[1].split('def _run',1)[0];assert text.index('provider.id in self.disabled') < text.index('self.observability.allowed(provider.id)')
