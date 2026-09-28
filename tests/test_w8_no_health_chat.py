from pathlib import Path

def test_health_check_never_calls_chat_method():
    health=Path('models/governed_router.py').read_text(encoding='utf-8').split('def health_status',1)[1];assert 'self.chat(' not in health
