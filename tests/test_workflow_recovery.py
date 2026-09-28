import sqlite3
import threading
import time

from agent.executor import ExecutionCancelled
from automation.engine import AutomationEngine


class ImmediateExecutor:
    def chat(self, prompt, cancel_event=None):
        return f'ok:{prompt}'


class BlockingExecutor:
    def __init__(self):
        self.started = threading.Event()

    def chat(self, prompt, cancel_event=None):
        self.started.set()
        while not cancel_event.wait(.01):
            pass
        raise ExecutionCancelled('cancelled')


def test_restart_requires_owner_review_then_resumes_from_checkpoint(tmp_path):
    path = tmp_path / 'workflows.sqlite3'
    first = AutomationEngine(path, executor=ImmediateExecutor())
    workflow_id = first.create_workflow('Recoverable', {'type': 'manual'}, [
        {'kind': 'set', 'key': 'one', 'value': 1},
        {'kind': 'set', 'key': 'two', 'value': 2},
    ])
    run_id = first.run_workflow(workflow_id)
    with sqlite3.connect(path) as con:
        con.execute(
            "UPDATE workflow_runs SET status='running',current_step=1,completed_at=NULL WHERE id=?",
            (run_id,),
        )

    reopened = AutomationEngine(path, executor=ImmediateExecutor())

    assert reopened.runs()[0]['status'] == 'recovery_required'
    result = reopened.resume_run(run_id, background=False)
    assert result['checkpoint'] == 1
    assert reopened.runs()[0]['status'] == 'completed'


def test_owner_cancellation_stops_active_workflow_cooperatively(tmp_path):
    executor = BlockingExecutor()
    engine = AutomationEngine(tmp_path / 'workflows.sqlite3', executor=executor)
    workflow_id = engine.create_workflow('Cancelable', {'type': 'manual'}, [
        {'kind': 'prompt', 'prompt': 'wait', 'retries': 0},
    ])
    run_id = engine.run_workflow(workflow_id, background=True)
    assert executor.started.wait(2)

    result = engine.cancel_run(run_id)
    assert result['status'] == 'cancelled'
    for _ in range(100):
        if engine.runs()[0]['status'] == 'cancelled':
            break
        time.sleep(.01)
    assert engine.runs()[0]['status'] == 'cancelled'


def test_cancelled_run_cannot_be_overwritten_as_completed(tmp_path):
    class SlowReturnExecutor:
        def __init__(self): self.started = threading.Event(); self.release = threading.Event()
        def chat(self, prompt, cancel_event=None):
            self.started.set(); self.release.wait(2); return 'late result'

    executor = SlowReturnExecutor();engine = AutomationEngine(tmp_path/'race.sqlite3',executor=executor)
    workflow_id=engine.create_workflow('Race safe',{'type':'manual'},[{'kind':'prompt','prompt':'wait','retries':0}])
    run_id=engine.run_workflow(workflow_id,background=True);assert executor.started.wait(2)
    engine.cancel_run(run_id);executor.release.set();time.sleep(.05)
    assert engine._run(run_id)['status']=='cancelled'
