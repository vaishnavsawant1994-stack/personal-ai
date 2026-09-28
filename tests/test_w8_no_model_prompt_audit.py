from pathlib import Path

def test_w8_audit_calls_pass_safe_metadata_only():
    text=Path('models/governed_router.py').read_text(encoding='utf-8');assert "_record('model.selected'" in text and "_record('model.error'" in text and 'prompt=' not in text
