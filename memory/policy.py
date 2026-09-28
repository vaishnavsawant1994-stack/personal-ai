from __future__ import annotations


NEVER_STORE = 'never_store'


def normalize_storage_policy(value) -> str:
    return str(value or '').strip().lower().replace('-', '_').replace(' ', '_')


def is_never_store(*, sensitivity=None, metadata=None) -> bool:
    if normalize_storage_policy(sensitivity) == NEVER_STORE:
        return True
    values = dict(metadata) if isinstance(metadata, dict) else {}
    return any(
        normalize_storage_policy(values.get(key)) == NEVER_STORE
        for key in ('storage_policy', 'retention_policy', 'memory_policy')
    )


def require_storable(*, sensitivity=None, metadata=None) -> None:
    if is_never_store(sensitivity=sensitivity, metadata=metadata):
        raise ValueError('NEVER_STORE content cannot be written to durable memory')
