from types import SimpleNamespace

import pytest

from automation.engine import AutomationEngine
from future_intelligence.everyday import EverydayIntelligence
from future_intelligence.operations_store import OperationStoreMixin
from integrations.state import ConnectorStateStore


def test_workflow_run_dynamic_columns_fail_closed_before_sql():
    engine = object.__new__(AutomationEngine)
    with pytest.raises(ValueError, match='invalid workflow run fields'):
        engine._update_run('run-1', **{'status=?, owner_id': 'malicious'})


def test_operation_dynamic_columns_fail_closed_before_sql():
    store = object.__new__(OperationStoreMixin)
    store._db = SimpleNamespace()
    with pytest.raises(ValueError, match='invalid operation update fields'):
        store._update_operation('operation-1', **{'status=?, owner_id': 'malicious'})


def test_everyday_transition_column_allowlist_excludes_untrusted_identifiers():
    assert 'status' in EverydayIntelligence.TRANSITION_FIELDS
    assert 'status=?, owner_id' not in EverydayIntelligence.TRANSITION_FIELDS


def test_oauth_invalidation_column_scope_fails_closed_before_sql():
    store = object.__new__(ConnectorStateStore)
    with pytest.raises(ValueError, match='invalid OAuth invalidation scope'):
        store._invalidate('device_id OR 1=1', 'device-1')
