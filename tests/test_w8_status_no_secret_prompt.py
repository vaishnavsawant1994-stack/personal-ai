from pathlib import Path

def test_status_implementation_has_no_prompt_or_message_storage():
    text=Path('models/resilience.py').read_text(encoding='utf-8')
    allow=text.split('SAFE_FIELDS =',1)[1].split('}',1)[0]
    assert 'prompt' not in allow and 'messages' not in allow and 'response' not in allow
