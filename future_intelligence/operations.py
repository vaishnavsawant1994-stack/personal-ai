from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from future_intelligence.operations_contract import OperationContractMixin, OperationStep
from future_intelligence.operations_runtime_helpers import OperationRuntimeHelperMixin
from future_intelligence.operations_runtime import OperationRuntimeMixin
from future_intelligence.operations_execute import OperationExecuteMixin
from future_intelligence.operations_control import OperationControlMixin
from future_intelligence.operations_recovery import OperationRecoveryMixin
from future_intelligence.operations_store import OperationStoreMixin
from future_intelligence.operations_outcomes import OperationOutcomeMixin


class PersonalOperations(OperationContractMixin, OperationRuntimeHelperMixin, OperationRecoveryMixin, OperationRuntimeMixin, OperationExecuteMixin, OperationControlMixin, OperationStoreMixin, OperationOutcomeMixin):
    """P6 owner-intent coordinator over existing governed execution authorities.

    This layer owns durable plan/delegation coordination only. Permission, approval,
    reauthentication, verification, retry/recovery authority and consequential action
    execution remain below it in the existing AgentExecutor/AutomationEngine/W7 stack.
    """

    ACTIVE = {'queued', 'executing', 'waiting_approval', 'waiting_reauth', 'verifying'}
    TERMINAL = {'verified', 'recovered', 'failed', 'cancelled'}
    RECOVERY = {'recovery_required'}
    OUTCOME_STATES = {'PLANNED', 'QUEUED', 'DISPATCHED', 'EXECUTED', 'VERIFIED', 'FAILED', 'UNCERTAIN', 'RECOVERED', 'CANCELLED'}
    PRIVATE_PARAMETER_MARKERS = {
        'token', 'password', 'secret', 'authorization', 'cookie', 'api_key',
        'apikey', 'credential', 'private_key', 'access_key', 'refresh_token',
    }
    DEFAULT_BUDGET = {
        'max_runtime_seconds': 900,
        'max_steps': 50,
        'max_retries': 0,
        'max_concurrent_runs': 2,
        'max_model_calls': 50,
        'max_tool_calls': 50,
        'approval_threshold': 'consequential',
        'owner_override_allowed': False,
    }

    def __init__(
        self,
        *,
        gate,
        executor=None,
        automations=None,
        events=None,
        second_brain=None,
        memory=None,
        everyday=None,
        path: Path | None = None,
    ):
        self.gate = gate
        self.executor = executor
        self.automations = automations
        self.events = events
        self.second_brain = second_brain
        self.memory = memory or getattr(executor, 'memory', None)
        self.everyday = everyday
        self._plans: dict[str, dict] = {}
        self._db = None
        self._locks: dict[str, threading.RLock] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self._db.row_factory = sqlite3.Row
            self._init_db()
            self._plans = {
                row['id']: json.loads(row['document'])
                for row in self._db.execute('SELECT id,document FROM operation_plans')
            }
            self._recover_interrupted()
