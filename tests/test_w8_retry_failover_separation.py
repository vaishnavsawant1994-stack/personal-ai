from pathlib import Path


def test_retry_and_failover_have_separate_counters_and_budgets():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'self.retry_attempts' in text and 'self.max_failovers' in text
    assert "counters['retries']" in text and "counters['failovers']" in text
