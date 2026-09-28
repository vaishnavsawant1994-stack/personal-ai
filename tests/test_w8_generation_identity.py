from models.resilience import ModelObservability


def test_generation_ids_are_unique_and_addressable():
    ids={ModelObservability.generation_id() for _ in range(100)}
    assert len(ids)==100 and all(value.startswith('gen_') for value in ids)
