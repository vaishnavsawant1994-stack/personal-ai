from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any


def now():
    return datetime.now(timezone.utc).isoformat()


class CapabilityLevel(IntEnum):
    NOT_SUPPORTED = 0
    PROTOTYPE = 1
    FUNCTIONAL = 2
    RELIABLE = 3
    PRODUCTION = 4
    SUPERIOR = 5

    @classmethod
    def label(cls, value: int):
        return cls(int(value)).name.replace('_', ' ').title()


@dataclass(frozen=True)
class BenchmarkResult:
    capability: str
    level: int
    label: str
    passed: int
    total: int
    latency_ms: float | None
    evidence: list[dict]


class CapabilityBenchmark:
    """Permanent P2.7 capability evidence and competitive-task registry.

    Structural probes can establish Functional behavior. Reliable/Production/
    Superior require explicit evidence flags or repeated external validation; the
    suite intentionally does not award those levels just because code exists.
    """

    CATEGORIES = (
        'voice',
        'screen_understanding',
        'computer_control',
        'browser_use',
        'files',
        'documents',
        'memory',
        'proactivity',
        'automation',
        'mobile',
        'cross_device',
        'security',
        'recovery',
        'latency',
        'reliability',
    )

    COMPETITIVE_TASKS = (
        'open_an_app',
        'inspect_the_screen',
        'research_something',
        'generate_a_document',
        'remember_a_preference',
        'recall_an_old_decision',
        'monitor_a_site',
        'execute_a_multi_step_task',
        'continue_on_another_device',
        'recover_from_failure',
        'request_permission_correctly',
    )

    def __init__(self, path: Path, *, runtime=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime or {}
        self._probes: dict[str, list[tuple[str, Callable[[], Any]]]] = {name: [] for name in self.CATEGORIES}
        self._register_default_probes()
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS capability_benchmark_runs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    latency_ms REAL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capability_task_evidence(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                '''
            )

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def register_probe(self, capability: str, name: str, probe: Callable[[], Any]):
        if capability not in self._probes:
            raise ValueError(f'unknown capability: {capability}')
        self._probes[capability].append((str(name), probe))

    def _tool_exists(self, name: str):
        tools = self.runtime.get('tools')
        if not tools:
            return False
        try:
            tools.get(name)
            return True
        except Exception:
            return False

    def _register_default_probes(self):
        self.register_probe('voice', 'voice runtime exists', lambda: bool(self.runtime.get('voice')))
        self.register_probe('voice', 'barge-in capable backend', lambda: hasattr(getattr(self.runtime.get('voice'), 'backend', None), 'cancel_response') or hasattr(getattr(self.runtime.get('voice'), 'backend', None), '_barge_in'))
        self.register_probe('screen_understanding', 'screen observer tool', lambda: self._tool_exists('computer_observe') or self._tool_exists('screen_understand'))
        self.register_probe('computer_control', 'verified computer executor', lambda: self._tool_exists('computer_execute'))
        self.register_probe('browser_use', 'browser navigation', lambda: self._tool_exists('browser_goto'))
        self.register_probe('browser_use', 'browser verification', lambda: self._tool_exists('browser_verify'))
        self.register_probe('files', 'file tools registered', lambda: any(self._tool_exists(name) for name in ('read_file', 'list_files', 'write_file')))
        self.register_probe('documents', 'document creation', lambda: any(self._tool_exists(name) for name in ('create_docx', 'create_pptx', 'create_xlsx')))
        self.register_probe('memory', 'second brain', lambda: bool(self.runtime.get('second_brain')))
        self.register_probe('memory', 'temporal memory', lambda: hasattr(self.runtime.get('second_brain'), 'temporal'))
        self.register_probe('proactivity', 'attention engine', lambda: bool(self.runtime.get('proactive')))
        self.register_probe('automation', 'workflow engine', lambda: hasattr(self.runtime.get('automations'), 'create_workflow'))
        self.register_probe('mobile', 'android companion runtime present', lambda: bool(self.runtime.get('device_registry')))
        self.register_probe('cross_device', 'continuity service', lambda: bool(self.runtime.get('continuity')))
        self.register_probe('security', 'central permission registry', lambda: bool(self.runtime.get('tools') and getattr(self.runtime['tools'], 'permissions', None)))
        self.register_probe('security', 'encrypted vault', lambda: bool(self.runtime.get('vault')))
        self.register_probe('recovery', 'backup service', lambda: bool(self.runtime.get('backups')))
        self.register_probe('latency', 'telemetry available', lambda: bool(self.runtime.get('telemetry')))
        self.register_probe('reliability', 'audit store available', lambda: bool(self.runtime.get('memory')))
        self.register_probe('reliability', 'automation recovery', lambda: hasattr(self.runtime.get('automations'), '_recover_interrupted_runs'))

    def run(self, capability: str, *, evidence_level: int | CapabilityLevel | None = None):
        if capability not in self._probes:
            raise ValueError(f'unknown capability: {capability}')
        started = time.perf_counter()
        evidence = []
        passed = 0
        for name, probe in self._probes[capability]:
            try:
                value = probe()
                ok = bool(value)
                detail = value if isinstance(value, (str, int, float, bool, type(None))) else type(value).__name__
            except Exception as exc:
                ok = False
                detail = f'{type(exc).__name__}: {exc}'
            passed += int(ok)
            evidence.append({'probe': name, 'passed': ok, 'detail': detail})
        total = len(evidence)
        if total == 0:
            structural = CapabilityLevel.NOT_SUPPORTED
        elif passed == 0:
            structural = CapabilityLevel.PROTOTYPE
        elif passed < total:
            structural = CapabilityLevel.PROTOTYPE
        else:
            structural = CapabilityLevel.FUNCTIONAL
        if evidence_level is None:
            level = structural
        else:
            requested = CapabilityLevel(int(evidence_level))
            if requested > CapabilityLevel.FUNCTIONAL:
                evidence.append({'probe': 'external_evidence_level', 'passed': True, 'detail': requested.name})
                level = requested if passed == total else min(requested, CapabilityLevel.PROTOTYPE)
            else:
                level = min(structural, requested)
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        result = BenchmarkResult(
            capability=capability,
            level=int(level),
            label=CapabilityLevel.label(int(level)),
            passed=passed,
            total=total,
            latency_ms=latency,
            evidence=evidence,
        )
        with self._con() as con:
            con.execute(
                'INSERT INTO capability_benchmark_runs(capability,level,passed,total,latency_ms,evidence_json,created_at) VALUES(?,?,?,?,?,?,?)',
                (capability, int(level), passed, total, latency, json.dumps(evidence, default=str), now()),
            )
        return asdict(result)

    def run_all(self):
        return {capability: self.run(capability) for capability in self.CATEGORIES}

    def record_task(self, task: str, status: str, evidence: dict | None = None):
        if task not in self.COMPETITIVE_TASKS:
            raise ValueError('unknown competitive task')
        normalized = str(status).strip().lower()
        if normalized not in {'not_supported', 'prototype', 'functional', 'reliable', 'production', 'superior', 'failed'}:
            raise ValueError('invalid task status')
        with self._con() as con:
            con.execute(
                'INSERT INTO capability_task_evidence(task,status,evidence_json,created_at) VALUES(?,?,?,?)',
                (task, normalized, json.dumps(evidence or {}, default=str), now()),
            )
        return {'task': task, 'status': normalized, 'evidence': evidence or {}}

    def latest(self):
        output = {}
        with self._con() as con:
            for capability in self.CATEGORIES:
                row = con.execute(
                    'SELECT * FROM capability_benchmark_runs WHERE capability=? ORDER BY id DESC LIMIT 1',
                    (capability,),
                ).fetchone()
                if row:
                    data = dict(row)
                    data['label'] = CapabilityLevel.label(data['level'])
                    data['evidence'] = json.loads(data.pop('evidence_json') or '[]')
                    output[capability] = data
        return output

    def task_matrix(self):
        matrix = []
        with self._con() as con:
            for task in self.COMPETITIVE_TASKS:
                row = con.execute(
                    'SELECT * FROM capability_task_evidence WHERE task=? ORDER BY id DESC LIMIT 1',
                    (task,),
                ).fetchone()
                matrix.append(
                    {
                        'task': task,
                        'status': row['status'] if row else 'not_supported',
                        'evidence': json.loads(row['evidence_json']) if row else {},
                        'updated_at': row['created_at'] if row else None,
                    }
                )
        return matrix
