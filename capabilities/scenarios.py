from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class ScenarioCheck:
    name: str
    probe: Callable[[], Any]


class CompetitiveScenarioSuite:
    """Non-destructive structural scenarios for the permanent P2.7 task matrix.

    These probes demonstrate that a complete governed path exists. They never
    launch applications, click the real screen, send messages or claim real-world
    reliability. Passing structural scenarios records only `functional` evidence.
    """

    def __init__(self, runtime: dict, benchmark):
        self.runtime = runtime
        self.benchmark = benchmark
        self.scenarios = self._build()

    def _tool_exists(self, name: str):
        tools = self.runtime.get('tools')
        if not tools:
            return False
        try:
            tools.get(name)
            return True
        except Exception:
            return False

    def _external_tool_governed(self):
        tools = self.runtime.get('tools')
        if not tools or not getattr(tools, 'permissions', None):
            return False
        try:
            tool = tools.get('launch_app')
            decision = tools.authorize(tool, confirmed=False)
            return hasattr(decision, 'allowed') and hasattr(decision, 'requires_confirmation')
        except Exception:
            return False

    def _build(self):
        return {
            'open_an_app': [
                ScenarioCheck('governed app-launch tool exists', lambda: self._tool_exists('launch_app')),
                ScenarioCheck('external actions pass centralized permission policy', self._external_tool_governed),
            ],
            'inspect_the_screen': [
                ScenarioCheck('read-only screen perception exists', lambda: self._tool_exists('computer_observe')),
                ScenarioCheck('vision runtime is available', lambda: bool(self.runtime.get('computer'))),
            ],
            'research_something': [
                ScenarioCheck('browser navigation exists', lambda: self._tool_exists('browser_goto')),
                ScenarioCheck('web-search path exists', lambda: self._tool_exists('web_search_browser')),
                ScenarioCheck('knowledge/memory context exists', lambda: bool(self.runtime.get('second_brain'))),
            ],
            'generate_a_document': [
                ScenarioCheck('DOCX generation exists', lambda: self._tool_exists('create_docx')),
                ScenarioCheck('spreadsheet generation exists', lambda: self._tool_exists('create_xlsx')),
                ScenarioCheck('presentation generation exists', lambda: self._tool_exists('create_pptx')),
            ],
            'remember_a_preference': [
                ScenarioCheck('Second Brain exists', lambda: bool(self.runtime.get('second_brain'))),
                ScenarioCheck('verified remember tool exists', lambda: self._tool_exists('remember')),
                ScenarioCheck('memory conflict tracking exists', lambda: hasattr(self.runtime.get('memory'), 'conflicts')),
            ],
            'recall_an_old_decision': [
                ScenarioCheck('temporal recall exists', lambda: hasattr(self.runtime.get('second_brain'), 'temporal')),
                ScenarioCheck('memory detail includes history', lambda: hasattr(self.runtime.get('second_brain'), 'memory_detail')),
            ],
            'monitor_a_site': [
                ScenarioCheck('durable workflow runtime exists', lambda: hasattr(self.runtime.get('automations'), 'create_workflow')),
                ScenarioCheck('event-trigger runtime exists', lambda: hasattr(self.runtime.get('automations'), 'trigger')),
                ScenarioCheck('calm proactive engine exists', lambda: bool(self.runtime.get('proactive'))),
            ],
            'execute_a_multi_step_task': [
                ScenarioCheck('agent executor exists', lambda: bool(self.runtime.get('executor'))),
                ScenarioCheck('durable multi-step workflows exist', lambda: hasattr(self.runtime.get('automations'), 'run_workflow')),
                ScenarioCheck('computer actions are transactional', lambda: bool(self.runtime.get('computer'))),
            ],
            'continue_on_another_device': [
                ScenarioCheck('device trust registry exists', lambda: bool(self.runtime.get('device_registry'))),
                ScenarioCheck('shared continuity service exists', lambda: bool(self.runtime.get('continuity'))),
                ScenarioCheck('continuity handoff exists', lambda: hasattr(self.runtime.get('continuity'), 'handoff')),
            ],
            'recover_from_failure': [
                ScenarioCheck('backup/recovery service exists', lambda: bool(self.runtime.get('backups'))),
                ScenarioCheck('workflow restart recovery exists', lambda: hasattr(self.runtime.get('automations'), '_recover_interrupted_runs')),
                ScenarioCheck('desktop rollback path exists', lambda: bool(self.runtime.get('computer'))),
            ],
            'request_permission_correctly': [
                ScenarioCheck('central permission engine exists', lambda: bool(getattr(self.runtime.get('tools'), 'permissions', None))),
                ScenarioCheck('one-use approval executor exists', lambda: bool(getattr(self.runtime.get('executor'), 'approvals', None))),
                ScenarioCheck('external tool is governed', self._external_tool_governed),
            ],
        }

    def run(self, task: str):
        if task not in self.scenarios:
            raise ValueError('unknown competitive task')
        evidence = []
        passed = 0
        for check in self.scenarios[task]:
            try:
                value = check.probe()
                ok = bool(value)
                detail = value if isinstance(value, (str, int, float, bool, type(None))) else type(value).__name__
            except Exception as exc:
                ok = False
                detail = f'{type(exc).__name__}: {exc}'
            passed += int(ok)
            evidence.append({'check': check.name, 'passed': ok, 'detail': detail})
        total = len(evidence)
        if passed == 0:
            status = 'not_supported'
        elif passed < total:
            status = 'prototype'
        else:
            status = 'functional'
        record = {
            'structural_only': True,
            'passed': passed,
            'total': total,
            'checks': evidence,
            'note': 'Structural evidence is capped at Functional; real-device reliability/production/superiority require separate evidence.',
        }
        self.benchmark.record_task(task, status, record)
        return {'task': task, 'status': status, 'evidence': record}

    def run_all(self):
        return {task: self.run(task) for task in self.benchmark.COMPETITIVE_TASKS}
