from pathlib import Path

def test_model_telemetry_allowlist_has_no_clipboard_or_dom_fields():
    allow=Path('models/resilience.py').read_text(encoding='utf-8').split('SAFE_FIELDS =',1)[1].split('}',1)[0].lower();assert 'clipboard' not in allow and 'dom' not in allow and 'screenshot' not in allow
