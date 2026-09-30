import pytest

from automation.engine import AutomationEngine


def test_disabled_execution_does_not_start_worker_or_accept_event_runs(tmp_path):
    engine = AutomationEngine(tmp_path / "automations.sqlite3", execution_enabled=False)
    workflow_id = engine.create_workflow(
        "qualification workflow",
        {"type": "event", "event": "qualification.test"},
        [{"kind": "prompt", "prompt": "must not execute"}],
    )

    assert engine.start() is False
    assert engine._thread is None
    assert engine.trigger("qualification.test", {"test": True}) == []
    with pytest.raises(RuntimeError, match="disabled for this installation"):
        engine.run_workflow(workflow_id)
    assert engine.runs(workflow_id) == []
    engine.stop()
