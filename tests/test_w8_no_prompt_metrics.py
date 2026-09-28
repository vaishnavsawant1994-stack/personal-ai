from pathlib import Path

def test_metrics_are_counts_timings_and_classifications_only():
    text=Path('models/resilience.py').read_text(encoding='utf-8').split('SAFE_FIELDS =',1)[1].split('}',1)[0]
    assert 'prompt' not in text and 'response' not in text and 'memory' not in text
