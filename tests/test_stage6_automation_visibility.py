from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from automation.engine import AutomationEngine
from automation.projection import AutomationWorkflowProjection
from security.request_context import TrustedRequestContext, reset_trusted_request, set_trusted_request
from server.automation_visibility_api import automation_visibility_router


class Devices:
    def __init__(self, active=True, allowed=True): self.active=active; self.allowed=allowed
    def is_active(self, device_id): return self.active and device_id == 'd1'
    def authorize(self, device_id, scope): return self.allowed and scope == 'workflow:read'


def context():
    return TrustedRequestContext(device_id='d1', session_id='s1', reauthenticated_at=None)


def engine(tmp_path):
    return AutomationEngine(tmp_path/'automations.sqlite3')


def test_projection_is_read_only_bounded_and_redacts_results(tmp_path):
    eng=engine(tmp_path)
    aid=eng.create('Daily','do work','2099-01-01T00:00:00+00:00',condition={'api_key':'x','safe':'yes'})
    with eng._con() as con:
        con.execute("UPDATE automations SET last_result_json=? WHERE id=?", ('{\"access_token\":\"secret\",\"approval_id\":\"A1\",\"reply\":\"ok\"}',aid))
    rows=AutomationWorkflowProjection(eng).automations()
    assert rows[0]['automation_id']==aid
    assert rows[0]['condition']['api_key']=='[redacted]'
    assert rows[0]['last_result']['access_token']=='[redacted]'
    assert rows[0]['approval_id']=='A1'
    assert 'prompt' not in rows[0]


def test_workflow_projection_does_not_expose_steps_or_prompts(tmp_path):
    eng=engine(tmp_path)
    wid=eng.create_workflow('Safe',{'type':'manual'},[{'kind':'prompt','prompt':'private instruction'}])
    row=AutomationWorkflowProjection(eng).workflows()[0]
    assert row['workflow_id']==wid and row['step_count']==1
    assert 'steps' not in row
    assert 'private instruction' not in str(row)


def test_run_visibility_is_owner_device_and_session_bound(tmp_path):
    eng=engine(tmp_path)
    wid=eng.create_workflow('Safe',{'type':'manual'},[{'kind':'set','key':'x','value':'y'}])
    run=eng.run_workflow(wid,owner_id='owner',device_id='d1',session_id='s1')
    projection=AutomationWorkflowProjection(eng)
    assert projection.runs(device_id='d1',session_id='s1')[0]['run_id']==run
    assert projection.runs(device_id='d2',session_id='s1')==[]
    assert projection.runs(device_id='d1',session_id='other')==[]


def test_api_requires_trusted_active_authorized_device(tmp_path):
    eng=engine(tmp_path)
    runtime={'automations':eng,'device_registry':Devices()}
    app=FastAPI(); app.include_router(automation_visibility_router(runtime)); client=TestClient(app)
    assert client.get('/iphone/api/automation-visibility/workflows').status_code==401
    token=set_trusted_request(context())
    try:
        assert client.get('/iphone/api/automation-visibility/workflows').status_code==200
        runtime['device_registry'].allowed=False
        assert client.get('/iphone/api/automation-visibility/workflows').status_code==403
        runtime['device_registry'].allowed=True; runtime['device_registry'].active=False
        assert client.get('/iphone/api/automation-visibility/workflows').status_code==401
    finally: reset_trusted_request(token)


def test_projection_does_not_create_second_scheduler_or_executor(tmp_path):
    eng=engine(tmp_path); projection=AutomationWorkflowProjection(eng)
    assert projection.engine is eng
    assert not hasattr(projection,'start')
    assert not hasattr(projection,'run_workflow')
    assert not hasattr(projection,'approve')


def test_run_projection_does_not_echo_free_form_provider_error(tmp_path):
    eng=engine(tmp_path)
    wid=eng.create_workflow('Safe',{'type':'manual'},[{'kind':'set','key':'x','value':'y'}])
    run=eng.run_workflow(wid,owner_id='owner',device_id='d1',session_id='s1')
    # runs() deliberately omits the raw error field. Simulate a canonical engine\n    # implementation that supplies one and prove the projection never echoes it.\n    original_runs=eng.runs\n    def runs_with_provider_error(*args,**kwargs):\n        rows=original_runs(*args,**kwargs)\n        rows[0]['error']='Authorization: Bearer secret-token https://example.invalid/?token=secret'\n        return rows\n    eng.runs=runs_with_provider_error\n    row=AutomationWorkflowProjection(eng).runs(device_id='d1',session_id='s1')[0]\n    assert row['error']=='Workflow run reported an error'\n    assert 'secret-token' not in str(row)
