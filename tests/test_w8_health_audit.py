from pathlib import Path

def test_circuit_transitions_are_auditable_safe_events():
    text=Path('models/governed_router.py').read_text(encoding='utf-8');assert "_record('model.circuit_transition'" in text
