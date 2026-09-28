from pathlib import Path

def test_router_does_not_guess_cost_from_model_name():
    text=Path('models/governed_router.py').read_text(encoding='utf-8').lower();assert 'price' not in text and 'cost_rank' not in text
