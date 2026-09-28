from pathlib import Path


def test_observability_is_read_only_with_respect_to_tools_and_operator():
    text=Path('models/resilience.py').read_text(encoding='utf-8')
    assert 'tools.' not in text and 'operator' not in text.lower() and 'subprocess' not in text
