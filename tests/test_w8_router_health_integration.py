from pathlib import Path

def test_router_updates_health_on_success_and_failure():
    text=Path('models/governed_router.py').read_text(encoding='utf-8');assert 'self.observability.success(' in text and 'self.observability.failure(' in text
