from pathlib import Path

def test_model_resilience_has_no_background_polling_thread():
    combined=Path('models/resilience.py').read_text(encoding='utf-8')+Path('models/governed_router.py').read_text(encoding='utf-8')
    assert 'Thread(' not in combined and 'while True' not in combined
