from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import server.workflow_budget_api as budget_api
from automation.budget import WorkflowBudgetError
from server.workflow_budget_ui import WorkflowBudgetUiMiddleware, workflow_budget_ui_router


class Registry:
    def authenticate(self, device, token):
        return device == 'd1' and token == 't1'

    def authorize(self, device, scope):
        return True


class Engine:
    def __init__(self):
        self.override_args = None

    def _run(self, run_id):
        if run_id == 'missing':
            raise KeyError(run_id)
        return {'id': run_id, 'device_id': 'd1', 'session_id': 's1'}

    def budget_status(self, run_id):
        return {
            'run_id': run_id,
            'policy': {'max_steps': 50},
            'consumption': {'model_calls': 1},
            'remaining': {'model_calls': 99},
            'confirmed_usage': False,
            'estimated_usage': {'input_tokens': 12, 'confirmed': False},
        }

    def override_run_budget(self, run_id, updates, **authority):
        self.override_args = (run_id, updates, authority)
        if updates.get('max_steps') == 999999:
            raise ValueError('max_steps must be between 1 and 500')
        if updates.get('deny'):
            raise PermissionError('owner override is disabled for this workflow')
        if updates.get('limit'):
            raise WorkflowBudgetError('Model-call limit reached', user_message='Model-call limit reached')
        return {'run_id': run_id, 'policy': updates}


def make_client(monkeypatch, reauth=123.0):
    engine = Engine()
    monkeypatch.setattr(
        budget_api,
        'current_trusted_request',
        lambda: SimpleNamespace(device_id='d1', session_id='s1', reauthenticated_at=reauth),
    )
    app = FastAPI()
    app.include_router(budget_api.workflow_budget_router({'device_registry': Registry(), 'automations': engine}))
    client = TestClient(app)
    client.cookies.set('pa_device', 'd1')
    client.cookies.set('pa_token', 't1')
    return client, engine


def test_budget_status_is_owner_visible_and_session_bound(monkeypatch):
    client, _ = make_client(monkeypatch)
    response = client.get('/iphone/api/workflows/runs/r1/budget')
    assert response.status_code == 200
    assert response.json()['estimated_usage']['confirmed'] is False


def test_override_propagates_session_and_maps_safe_http_states(monkeypatch):
    client, engine = make_client(monkeypatch, 456.0)
    response = client.post(
        '/iphone/api/workflows/runs/r1/budget/override',
        json={'updates': {'max_model_calls': 150}},
    )
    assert response.status_code == 200
    assert engine.override_args[2] == {
        'owner_id': 'owner',
        'device_id': 'd1',
        'session_id': 's1',
        'reauthenticated_at': 456.0,
    }
    assert client.post('/iphone/api/workflows/runs/r1/budget/override', json={'updates': {'limit': True}}).status_code == 409
    assert client.post('/iphone/api/workflows/runs/r1/budget/override', json={'updates': {'deny': True}}).status_code == 403
    assert client.post('/iphone/api/workflows/runs/r1/budget/override', json={'updates': {'max_steps': 999999}}).status_code == 422


def test_budget_ui_is_injected_only_into_iphone_home_and_keeps_safe_states():
    app = FastAPI()
    app.add_middleware(WorkflowBudgetUiMiddleware)
    app.include_router(workflow_budget_ui_router())

    @app.get('/iphone')
    def home():
        return HTMLResponse('<html><body><main id="home">Home</main></body></html>')

    @app.get('/other')
    def other():
        return HTMLResponse('<html><body>Other</body></html>')

    client = TestClient(app)
    home_html = client.get('/iphone').text
    assert '<main id="home">Home</main>' in home_html
    assert '/iphone/workflow-budget-ui.js' in home_html
    assert '/iphone/workflow-budget-ui.js' not in client.get('/other').text
    javascript = client.get('/iphone/workflow-budget-ui.js').text
    for label in (
        'Workflow limit reached',
        'Maximum runtime reached',
        'Concurrent run limit reached',
        'Model-call limit reached',
        'Tool-call limit reached',
        'Token/cost budget unavailable',
        'Waiting for approval',
        'Recovery review required',
        'Cancelled by owner',
        'Emergency Stop active',
    ):
        assert label in javascript
