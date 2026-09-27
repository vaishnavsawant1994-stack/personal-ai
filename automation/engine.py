from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.executor import ConfirmationRequired, ExecutionCancelled
from automation.conditions import evaluate_condition


def now():
    return datetime.now(timezone.utc).isoformat()


def now_ts():
    return datetime.now(timezone.utc).timestamp()


class AutomationEngine:
    """Scheduled automations plus durable multi-step P2.4 workflows."""

    def __init__(
        self,
        path: Path,
        executor=None,
        events=None,
        poll_seconds: float = 2.0,
        context_provider=None,
        default_timeout_seconds: int = 120,
        default_retries: int = 2,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.events = events
        self.poll_seconds = poll_seconds
        self.context_provider = context_provider or (lambda: {})
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))
        self.default_retries = max(0, int(default_retries))
        self._stop = threading.Event()
        self._thread = None
        # Keep orchestration workers separate from timed agent-step workers.
        # A workflow worker may block waiting for a prompt future; sharing one
        # pool can therefore starve the very prompt future it is waiting on.
        self._workflow_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='personal-ai-workflow')
        self._step_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='personal-ai-workflow-step')
        self._run_locks: dict[str, threading.Lock] = {}
        self._init_db()
        self._recover_interrupted_runs()
        if self.events:
            self.events.subscribe('automation.trigger', self._on_trigger_event)

    def _init_db(self):
        with self._con() as con:
            con.execute(
                'CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY,title TEXT,prompt TEXT,next_run_at TEXT,interval_seconds INTEGER,enabled INTEGER,last_run_at TEXT,created_at TEXT)'
            )
            cols = {row['name'] for row in con.execute('PRAGMA table_info(automations)')}
            if 'condition_json' not in cols:
                con.execute("ALTER TABLE automations ADD COLUMN condition_json TEXT DEFAULT '{}'")
            if 'last_result_json' not in cols:
                con.execute('ALTER TABLE automations ADD COLUMN last_result_json TEXT')
            con.execute(
                '''CREATE TABLE IF NOT EXISTS workflows(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    trigger_json TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    paused INTEGER NOT NULL DEFAULT 0,
                    next_run_at TEXT,
                    interval_seconds INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT
                )'''
            )
            con.execute(
                '''CREATE TABLE IF NOT EXISTS workflow_runs(
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_json TEXT,
                    context_json TEXT,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    completed_steps_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT,
                    error TEXT,
                    pending_approval_id TEXT,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
                )'''
            )
            con.execute('CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow ON workflow_runs(workflow_id,started_at)')

    def _recover_interrupted_runs(self):
        with self._con() as con:
            con.execute(
                "UPDATE workflow_runs SET status='interrupted',error='runtime restarted during active workflow',updated_at=?,completed_at=? WHERE status IN ('running','rolling_back')",
                (now(), now()),
            )

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------------
    # Legacy scheduled prompt automations (kept for compatibility)
    # ------------------------------------------------------------------
    def create(self, title, prompt, next_run_at, interval_seconds=None, condition=None):
        automation_id = str(uuid.uuid4())
        with self._con() as con:
            con.execute(
                'INSERT INTO automations(id,title,prompt,next_run_at,interval_seconds,enabled,last_run_at,created_at,condition_json) VALUES(?,?,?,?,?,1,NULL,?,?)',
                (
                    automation_id,
                    title,
                    prompt,
                    next_run_at,
                    interval_seconds,
                    now(),
                    json.dumps(condition or {}),
                ),
            )
        return automation_id

    def list(self):
        with self._con() as con:
            return [dict(row) for row in con.execute('SELECT * FROM automations ORDER BY created_at DESC')]

    def enable(self, automation_id, enabled=True):
        with self._con() as con:
            con.execute('UPDATE automations SET enabled=? WHERE id=?', (int(enabled), automation_id))

    # ------------------------------------------------------------------
    # P2.4 workflows
    # ------------------------------------------------------------------
    def create_workflow(self, title: str, trigger: dict, steps: list[dict], *, next_run_at: str | None = None, interval_seconds: int | None = None):
        trigger = dict(trigger or {})
        trigger_type = str(trigger.get('type', 'event'))
        if trigger_type not in {'event', 'schedule', 'manual'}:
            raise ValueError('workflow trigger type must be event, schedule or manual')
        if not steps:
            raise ValueError('workflow requires at least one step')
        normalized = [self._normalize_step(step, i) for i, step in enumerate(steps)]
        if len(normalized) > 50:
            raise ValueError('workflow may contain at most 50 steps')
        if trigger_type == 'schedule' and not next_run_at:
            next_run_at = str(trigger.get('next_run_at') or '')
            if not next_run_at:
                raise ValueError('scheduled workflow requires next_run_at')
        workflow_id = str(uuid.uuid4())
        stamp = now()
        with self._con() as con:
            con.execute(
                '''INSERT INTO workflows(id,title,trigger_json,steps_json,enabled,paused,next_run_at,interval_seconds,created_at,updated_at,last_run_at)
                   VALUES(?,?,?,?,1,0,?,?,?,?,NULL)''',
                (workflow_id, str(title), json.dumps(trigger), json.dumps(normalized), next_run_at, interval_seconds, stamp, stamp),
            )
        self._emit('workflow.created', workflow_id=workflow_id, title=title)
        return workflow_id

    def _normalize_step(self, step: dict, position: int):
        row = dict(step or {})
        kind = str(row.get('kind', 'prompt')).strip().lower()
        if kind not in {'prompt', 'condition', 'set', 'emit'}:
            raise ValueError(f'unsupported workflow step kind: {kind}')
        row['kind'] = kind
        row['position'] = int(position)
        row['retries'] = max(0, min(int(row.get('retries', self.default_retries)), 10))
        row['timeout_seconds'] = max(1, min(int(row.get('timeout_seconds', self.default_timeout_seconds)), 3600))
        if kind == 'prompt' and not str(row.get('prompt', '')).strip():
            raise ValueError('prompt workflow step requires prompt')
        if kind == 'condition' and not isinstance(row.get('condition'), dict):
            raise ValueError('condition workflow step requires condition object')
        if kind == 'set' and not str(row.get('key', '')).strip():
            raise ValueError('set workflow step requires key')
        if kind == 'emit' and not str(row.get('event', '')).strip():
            raise ValueError('emit workflow step requires event')
        return row

    def workflows(self):
        with self._con() as con:
            rows = [dict(row) for row in con.execute('SELECT * FROM workflows ORDER BY created_at DESC')]
        for row in rows:
            row['trigger'] = json.loads(row.pop('trigger_json') or '{}')
            row['steps'] = json.loads(row.pop('steps_json') or '[]')
        return rows

    def workflow(self, workflow_id: str):
        with self._con() as con:
            row = con.execute('SELECT * FROM workflows WHERE id=?', (workflow_id,)).fetchone()
        if not row:
            raise KeyError('workflow not found')
        data = dict(row)
        data['trigger'] = json.loads(data.pop('trigger_json') or '{}')
        data['steps'] = json.loads(data.pop('steps_json') or '[]')
        return data

    def pause_workflow(self, workflow_id: str, paused: bool = True):
        with self._con() as con:
            cur = con.execute('UPDATE workflows SET paused=?,updated_at=? WHERE id=?', (int(paused), now(), workflow_id))
        if cur.rowcount != 1:
            raise KeyError('workflow not found')
        self._emit('workflow.paused' if paused else 'workflow.resumed', workflow_id=workflow_id)
        return {'workflow_id': workflow_id, 'paused': bool(paused)}

    def enable_workflow(self, workflow_id: str, enabled: bool = True):
        with self._con() as con:
            cur = con.execute('UPDATE workflows SET enabled=?,updated_at=? WHERE id=?', (int(enabled), now(), workflow_id))
        if cur.rowcount != 1:
            raise KeyError('workflow not found')
        return {'workflow_id': workflow_id, 'enabled': bool(enabled)}

    def trigger(self, event_name: str, payload: dict | None = None):
        payload = dict(payload or {})
        matches = []
        for workflow in self.workflows():
            if not workflow['enabled'] or workflow['paused']:
                continue
            trigger = workflow['trigger']
            if trigger.get('type', 'event') != 'event' or str(trigger.get('event')) != str(event_name):
                continue
            condition = trigger.get('condition') or {}
            context = {**(self.context_provider() or {}), 'event': payload, 'trigger': {'name': event_name}}
            if condition and not evaluate_condition(condition, context):
                continue
            run_id = self.run_workflow(workflow['id'], trigger_payload={'event': event_name, 'payload': payload}, context=context, background=True)
            matches.append(run_id)
        return matches

    def _on_trigger_event(self, event):
        event_name = str(event.get('name') or event.get('trigger') or '')
        if event_name:
            self.trigger(event_name, dict(event.get('payload') or {}))

    def run_workflow(self, workflow_id: str, *, trigger_payload=None, context=None, background=False):
        workflow = self.workflow(workflow_id)
        if not workflow['enabled']:
            raise RuntimeError('workflow is disabled')
        if workflow['paused']:
            raise RuntimeError('workflow is paused')
        run_id = str(uuid.uuid4())
        run_context = {**(self.context_provider() or {}), **(context or {})}
        stamp = now()
        with self._con() as con:
            con.execute(
                '''INSERT INTO workflow_runs(id,workflow_id,status,trigger_json,context_json,current_step,completed_steps_json,result_json,error,pending_approval_id,started_at,updated_at,completed_at)
                   VALUES(?,?, 'queued', ?, ?, 0, '[]', NULL, NULL, NULL, ?, ?, NULL)''',
                (run_id, workflow_id, json.dumps(trigger_payload or {}), json.dumps(run_context, default=str), stamp, stamp),
            )
        if background:
            self._workflow_pool.submit(self._continue_run, run_id)
        else:
            self._continue_run(run_id)
        return run_id

    def _continue_run(self, run_id: str, *, approved_result=None):
        lock = self._run_locks.setdefault(run_id, threading.Lock())
        if not lock.acquire(blocking=False):
            return
        try:
            run = self._run(run_id)
            if run['status'] in {'completed', 'failed', 'cancelled', 'interrupted'}:
                return
            workflow = self.workflow(run['workflow_id'])
            steps = workflow['steps']
            context = json.loads(run['context_json'] or '{}')
            completed = json.loads(run['completed_steps_json'] or '[]')
            index = int(run['current_step'])
            if approved_result is not None:
                completed.append({'step': index, 'kind': 'approval_resume', 'result': approved_result})
                index += 1
            self._update_run(run_id, status='running', current_step=index, completed_steps_json=json.dumps(completed), pending_approval_id=None)
            self._emit('workflow.started', run_id=run_id, workflow_id=workflow['id'], title=workflow['title'])
            while index < len(steps):
                step = steps[index]
                try:
                    result = self._execute_workflow_step(run_id, step, context)
                except ConfirmationRequired as approval:
                    self._update_run(run_id, status='waiting_approval', current_step=index, context_json=json.dumps(context, default=str), completed_steps_json=json.dumps(completed, default=str), pending_approval_id=approval.approval_id)
                    self._emit('workflow.approval_required', run_id=run_id, workflow_id=workflow['id'], approval_id=approval.approval_id, tool=approval.tool_name)
                    return
                except Exception as exc:
                    rollback = self._rollback(workflow, completed, context)
                    self._update_run(run_id, status='failed', error=str(exc), context_json=json.dumps(context, default=str), completed_steps_json=json.dumps(completed, default=str), result_json=json.dumps({'rollback': rollback}, default=str), completed_at=now())
                    self._emit('workflow.failed', run_id=run_id, workflow_id=workflow['id'], error=str(exc), rollback=rollback)
                    return
                completed.append({'step': index, 'kind': step['kind'], 'result': result})
                context[f'step_{index + 1}'] = result
                index += 1
                self._update_run(run_id, current_step=index, context_json=json.dumps(context, default=str), completed_steps_json=json.dumps(completed, default=str))
                self._emit('workflow.step.completed', run_id=run_id, workflow_id=workflow['id'], step=index, kind=step['kind'])
            result = {'completed_steps': completed, 'context': context}
            self._update_run(run_id, status='completed', result_json=json.dumps(result, default=str), completed_at=now())
            with self._con() as con:
                con.execute('UPDATE workflows SET last_run_at=?,updated_at=? WHERE id=?', (now(), now(), workflow['id']))
            self._emit('workflow.completed', run_id=run_id, workflow_id=workflow['id'], result=result)
        finally:
            lock.release()

    def _execute_workflow_step(self, run_id: str, step: dict, context: dict):
        kind = step['kind']
        if kind == 'condition':
            return {'matched': evaluate_condition(step['condition'], context)}
        if kind == 'set':
            value = step.get('value')
            context[str(step['key'])] = value
            return {'key': str(step['key']), 'value': value}
        if kind == 'emit':
            payload = dict(step.get('payload') or {})
            if self.events:
                self.events.emit(str(step['event']), run_id=run_id, **payload)
            return {'emitted': str(step['event'])}
        if kind != 'prompt':
            raise ValueError(f'unsupported workflow step kind: {kind}')
        if not self.executor:
            raise RuntimeError('workflow executor unavailable')
        prompt = self._render(str(step['prompt']), context)
        retries = int(step.get('retries', self.default_retries))
        timeout = int(step.get('timeout_seconds', self.default_timeout_seconds))
        last_error = None
        for attempt in range(retries + 1):
            cancel_event = threading.Event()
            future = self._step_pool.submit(self.executor.chat, prompt, cancel_event=cancel_event)
            try:
                reply = future.result(timeout=timeout)
                return {'reply': reply, 'attempt': attempt + 1}
            except FutureTimeout:
                cancel_event.set()
                last_error = TimeoutError(f'workflow step timed out after {timeout}s')
            except ConfirmationRequired:
                raise
            except ExecutionCancelled as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
            if attempt < retries:
                self._emit('workflow.step.retry', run_id=run_id, attempt=attempt + 1, error=str(last_error))
                time.sleep(min(2 ** attempt, 5))
        raise RuntimeError(str(last_error or 'workflow step failed'))

    @staticmethod
    def _render(text: str, context: dict):
        rendered = text
        for key, value in context.items():
            token = '{{' + str(key) + '}}'
            if token in rendered:
                rendered = rendered.replace(token, str(value))
        return rendered

    def approve_run(self, run_id: str, approval_id: str):
        run = self._run(run_id)
        if run['status'] != 'waiting_approval' or run['pending_approval_id'] != approval_id:
            raise PermissionError('run is not waiting for this approval')
        result = self.executor.approve(approval_id)
        self._update_run(run_id, status='queued', pending_approval_id=None)
        self._workflow_pool.submit(self._continue_run, run_id, approved_result=result)
        return {'run_id': run_id, 'approval_id': approval_id, 'resumed': True}

    def reject_run(self, run_id: str, approval_id: str):
        run = self._run(run_id)
        if run['status'] != 'waiting_approval' or run['pending_approval_id'] != approval_id:
            raise PermissionError('run is not waiting for this approval')
        self.executor.reject(approval_id)
        self._update_run(run_id, status='cancelled', pending_approval_id=None, completed_at=now(), error='user rejected approval')
        self._emit('workflow.cancelled', run_id=run_id, workflow_id=run['workflow_id'], reason='approval_rejected')
        return {'run_id': run_id, 'cancelled': True}

    def _rollback(self, workflow: dict, completed: list[dict], context: dict):
        results = []
        by_position = {int(step['position']): step for step in workflow['steps']}
        for item in reversed(completed):
            step = by_position.get(int(item.get('step', -1)))
            if not step or not step.get('rollback_prompt') or not self.executor:
                continue
            prompt = self._render(str(step['rollback_prompt']), context)
            try:
                reply = self.executor.chat(prompt)
                results.append({'step': item.get('step'), 'ok': True, 'reply': reply})
            except Exception as exc:
                results.append({'step': item.get('step'), 'ok': False, 'error': str(exc)})
        return results

    def _run(self, run_id: str):
        with self._con() as con:
            row = con.execute('SELECT * FROM workflow_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise KeyError('workflow run not found')
        return dict(row)

    def runs(self, workflow_id: str | None = None, limit: int = 100):
        limit = max(1, min(int(limit), 1000))
        with self._con() as con:
            if workflow_id:
                rows = con.execute('SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?', (workflow_id, limit)).fetchall()
            else:
                rows = con.execute('SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(row) for row in rows]

    def _update_run(self, run_id: str, **fields):
        if not fields:
            return
        fields['updated_at'] = now()
        columns = ','.join(f'{key}=?' for key in fields)
        values = list(fields.values()) + [run_id]
        with self._con() as con:
            con.execute(f'UPDATE workflow_runs SET {columns} WHERE id=?', values)

    def _emit(self, event, **payload):
        if self.events:
            self.events.emit(event, **payload)

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='personal-ai-automation')
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))
        self._workflow_pool.shutdown(wait=False, cancel_futures=True)
        self._step_pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            if self.executor:
                with self._con() as con:
                    due = con.execute('SELECT * FROM automations WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at', (now(),)).fetchall()
                for row in due:
                    self._run_one(row)
            self._run_due_workflows()

    def _run_due_workflows(self):
        with self._con() as con:
            rows = con.execute('SELECT * FROM workflows WHERE enabled=1 AND paused=0 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at', (now(),)).fetchall()
        for row in rows:
            workflow_id = row['id']
            self.run_workflow(workflow_id, trigger_payload={'type': 'schedule'}, background=True)
            if row['interval_seconds']:
                next_at = datetime.fromtimestamp(now_ts() + int(row['interval_seconds']), timezone.utc).isoformat()
                with self._con() as con:
                    con.execute('UPDATE workflows SET next_run_at=?,updated_at=? WHERE id=?', (next_at, now(), workflow_id))
            else:
                with self._con() as con:
                    con.execute('UPDATE workflows SET next_run_at=NULL,updated_at=? WHERE id=?', (now(), workflow_id))

    def _run_one(self, row):
        result = {'executed': False}
        try:
            condition = json.loads(row['condition_json'] or '{}')
            context = self.context_provider() or {}
            if condition and not evaluate_condition(condition, context):
                result = {'executed': False, 'reason': 'condition_false'}
                self._emit('automation.skipped', automation_id=row['id'])
            else:
                reply = self.executor.chat(row['prompt'])
                result = {'executed': True, 'reply': reply}
                self._emit('automation.completed', automation_id=row['id'])
        except ConfirmationRequired as approval:
            result = {'executed': False, 'reason': 'approval_required', 'approval_id': approval.approval_id}
            self._emit('automation.approval_required', automation_id=row['id'], approval_id=approval.approval_id, tool=approval.tool_name)
        except Exception as exc:
            result = {'executed': False, 'error': str(exc)}
            self._emit('automation.failed', automation_id=row['id'], error=str(exc))
        finally:
            with self._con() as con:
                if row['interval_seconds']:
                    next_at = datetime.fromtimestamp(now_ts() + row['interval_seconds'], timezone.utc).isoformat()
                    con.execute('UPDATE automations SET last_run_at=?,next_run_at=?,last_result_json=? WHERE id=?', (now(), next_at, json.dumps(result), row['id']))
                else:
                    con.execute('UPDATE automations SET last_run_at=?,enabled=0,last_result_json=? WHERE id=?', (now(), json.dumps(result), row['id']))
