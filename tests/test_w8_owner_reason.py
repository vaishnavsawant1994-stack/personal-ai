from pathlib import Path

def test_owner_status_can_show_routing_reason_without_prompt():
    text=Path('models/resilience.py').read_text(encoding='utf-8').split('SAFE_FIELDS =',1)[1].split('}',1)[0];assert 'routing_reason' in text and 'prompt' not in text
