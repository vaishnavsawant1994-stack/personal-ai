from pathlib import Path


def test_observability_never_records_raw_model_response():
    text=Path('models/governed_router.py').read_text(encoding='utf-8')
    for call in text.split('add_generation(')[1:]:
        segment=call.split(')',1)[0]
        assert "'response':" not in segment and "'prompt':" not in segment and "'messages':" not in segment
