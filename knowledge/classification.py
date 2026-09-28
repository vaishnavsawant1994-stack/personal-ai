"""Authoritative source classification for Knowledge.

The stored access class must be at least as restrictive as the source
minimum. A caller cannot lower it. Caller metadata is not the read.
"""

from __future__ import annotations

# Higher means more restrictive. `public` is a request alias, not a stored class.
_RANK = {
    'public': 0,
    'owner': 1,
    'trusted-devices': 2,
    'private': 3,
    'sensitive': 3,
    'restricted': 3,
    'secret': 4,
    'never_store': 5,
}
STORED_CLASSES = {'owner', 'trusted-devices', 'private'}
CONNECTOR_PREFIXES = ('google-', 'connector:')


def classification_rank(value: str) -> int:
    key = str(value or '').strip().lower().replace('_', '-')
    if key not in _RANK:
        raise ValueError('Invalid knowledge access class')
    return _RANK[key]


def is_connector_source(source: str) -> bool:
    return str(source or '').startswith(CONNECTOR_PREFIXES)


def enforce_source_minimum(requested: str, source_minimum: str) -> str:
    """Return the stored class, or raise if the request would weaken the source."""
    if classification_rank(source_minimum) >= _RANK['secret']:
        raise ValueError('This source cannot be stored without weakening its classification')
    if classification_rank(requested) < classification_rank(source_minimum):
        raise ValueError('Knowledge classification cannot be lower than the source classification')
    stored = str(requested or '').strip().lower().replace('_', '-')
    if stored == 'public':
        stored = 'owner'
    if stored in {'sensitive', 'restricted'}:
        stored = 'private'
    if stored not in STORED_CLASSES:
        raise ValueError('Invalid knowledge access class')
    return stored


def connector_source_minimum(item: dict | None) -> str:
    """The read carries the minimum. A missing classification stays private."""
    payload = dict(item or {})
    provenance = dict(payload.get('provenance') or {})
    raw = provenance.get('source_classification', payload.get('source_classification'))
    if raw is None or not str(raw).strip():
        return 'private'
    return str(raw).strip().lower().replace('_', '-')


def floor_for_source(
    source: str,
    metadata: dict | None = None,
    *,
    source_minimum: str | None = None,
    trust_recorded: bool = False,
) -> str | None:
    """Floor for this write.

    `source_minimum` is the connector read. A recorded floor is trusted only
    for a document Knowledge already stored. Caller metadata cannot create a
    weaker floor, and a connector source with no classification is private.
    """
    meta = dict(metadata or {})
    if source_minimum is not None and str(source_minimum).strip():
        key = str(source_minimum).strip().lower().replace('_', '-')
        classification_rank(key)
        return key
    if trust_recorded:
        recorded = meta.get('source_minimum_classification')
        if recorded is not None and str(recorded).strip():
            key = str(recorded).strip().lower().replace('_', '-')
            classification_rank(key)
            return key
    if is_connector_source(source):
        return 'private'
    return None
