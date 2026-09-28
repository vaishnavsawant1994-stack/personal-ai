from __future__ import annotations

from types import SimpleNamespace

from apps_tools.projection import AppsToolsProjection
from tools.registry import Risk, Tool


class Permissions:
    def decide(self, risk, confirmed=False):
        return SimpleNamespace(allowed=risk == 0, needs_confirmation=risk > 0)


class Tools:
    def __init__(self, values):
        self.values = {tool.name: tool for tool in values}
        self.permissions = Permissions()
    def all(self): return list(self.values.values())
    def get(self, name): return self.values[name]


class Integrations:
    def __init__(self, rows): self.rows = rows
    def list(self): return list(self.rows)


def tool(name='gmail.send', **kwargs):
    return Tool(name=name, description=kwargs.pop('description', 'Send mail'), handler=lambda p: None, **kwargs)


def test_projection_never_exposes_handlers_or_private_tool_internals():
    registry = Tools([tool(capability='send_mail', connector_id='gmail', risk=Risk.EXTERNAL_SIDE_EFFECT)])
    integrations = Integrations([{'id':'gmail','name':'Gmail','provider':'google','configured':True,'state':'healthy','capabilities':['gmail.send']}])
    item = AppsToolsProjection(registry, integrations).tools_list()[0]
    assert item['tool_id'] == 'gmail.send'
    assert item['availability'] == 'AVAILABLE'
    assert item['approval_policy'] == 'approval_required'
    assert 'handler' not in item and 'verifier' not in item and 'rollback' not in item


def test_registered_connector_is_not_falsely_connected_when_unconfigured():
    registry = Tools([tool(connector_id='gmail')])
    integrations = Integrations([{'id':'gmail','name':'Gmail','provider':'google','configured':False,'state':'not_configured','capabilities':['gmail.read']}])
    projection = AppsToolsProjection(registry, integrations)
    assert projection.tools_list()[0]['availability'] == 'NOT_CONFIGURED'
    app = projection.apps_list()[0]
    assert app['configured'] is False
    assert app['connection_status'] == 'not_configured'
    assert app['authorization_required'] is False


def test_connection_and_permission_states_derive_from_lifecycle_truth():
    states = {
        'healthy':'AVAILABLE', 'authentication_required':'CONNECTION_REQUIRED',
        'authentication_expired':'CONNECTION_REQUIRED', 'revoked':'CONNECTION_REQUIRED',
        'insufficient_scope':'PERMISSION_BLOCKED', 'permission_denied':'PERMISSION_BLOCKED',
        'degraded':'ERROR', 'provider_unavailable':'ERROR', 'disabled':'PERMISSION_BLOCKED',
    }
    for state, expected in states.items():
        registry = Tools([tool(connector_id='gmail')])
        integrations = Integrations([{'id':'gmail','name':'Gmail','provider':'google','configured':True,'state':state}])
        assert AppsToolsProjection(registry, integrations).tools_list()[0]['availability'] == expected


def test_prohibited_tool_is_permission_blocked_and_policy_blocked():
    item = AppsToolsProjection(Tools([tool(prohibited=True)]), Integrations([])).tools_list()[0]
    assert item['availability'] == 'PERMISSION_BLOCKED'
    assert item['approval_policy'] == 'blocked_by_policy'


def test_reauth_requirement_is_preserved():
    item = AppsToolsProjection(Tools([tool(requires_reauth=True, risk=Risk.DESTRUCTIVE)]), Integrations([])).tools_list()[0]
    assert item['requires_reauth'] is True
    assert item['approval_policy'] == 'reauth_required'


def test_app_projection_is_bounded_and_does_not_forward_credentials():
    rows = [{
        'id':'gmail','name':'Gmail','provider':'google','configured':True,'state':'healthy',
        'capabilities':[f'op{i}' for i in range(300)], 'missing_scopes':[f's{i}' for i in range(300)],
        'access_token':'secret','refresh_token':'secret','client_secret':'secret','credential':'secret',
        'last_error':'x'*2000,'last_error_code':'bad','revocation_status':'none','read_only':False,
    }]
    item = AppsToolsProjection(Tools([]), Integrations(rows)).apps_list()[0]
    assert len(item['capabilities']) == 100
    assert len(item['missing_scopes']) == 100
    assert item['last_error'] == 'Connector reported an error'
    for secret in ('access_token','refresh_token','client_secret','credential'):
        assert secret not in item


def test_missing_tool_and_app_fail_as_not_found_projection():
    projection = AppsToolsProjection(Tools([]), Integrations([]))
    assert projection.tool_detail('missing') is None
    assert projection.app_detail('missing') is None


def test_tool_identity_is_stable_backend_name():
    registry = Tools([tool(name='files.read'), tool(name='gmail.send')])
    projection = AppsToolsProjection(registry, Integrations([]))
    first = {x['tool_id'] for x in projection.tools_list()}
    second = {x['tool_id'] for x in AppsToolsProjection(registry, Integrations([])).tools_list()}
    assert first == second == {'files.read','gmail.send'}


def test_large_registry_is_bounded():
    registry = Tools([tool(name=f'tool.{i}') for i in range(250)])
    assert len(AppsToolsProjection(registry, Integrations([])).tools_list()) == 200


def test_malicious_metadata_remains_plain_bounded_text():
    bad = '<script>alert(1)</script>javascript:evil()'
    item = AppsToolsProjection(Tools([tool(name=bad, description=bad*100)]), Integrations([])).tools_list()[0]
    assert item['name'] == bad
    assert len(item['description']) <= 1000
    assert '<script>' in item['name']  # API returns data, never executable markup.


def test_emergency_stop_is_visible_and_blocks_tool_availability():
    registry = Tools([tool(name='local.action', risk=Risk.READ_ONLY)])
    registry.emergency_stop = True
    item = AppsToolsProjection(registry, Integrations([])).tools_list()[0]
    assert item['availability'] == 'EMERGENCY_STOP'
    assert item['approval_policy'] == 'blocked_by_emergency_stop'


def test_free_form_provider_error_cannot_echo_secrets():
    secret = 'Bearer super-secret-access-token'
    rows = [{
        'id':'gmail','name':'Gmail','provider':'google','configured':True,'state':'degraded',
        'last_error':f'Authorization: {secret}; https://example.invalid/?token={secret}',
        'last_error_code':'provider_error',
    }]
    item = AppsToolsProjection(Tools([]), Integrations(rows)).apps_list()[0]
    assert secret not in str(item)
    assert item['last_error'] == 'Connector reported an error'
    assert item['last_error_code'] == 'provider_error'


def test_apps_tools_projection_never_invokes_execution_preparation():
    prepared={'count':0}
    def prepare(parameters, context=None):
        prepared['count'] += 1
        raise AssertionError('metadata projection must not prepare execution')
    prepared_tool=Tool('prepared_tool','safe metadata',lambda p:{'ok':True},Risk.READ_ONLY,prepare=prepare)
    registry=Tools([prepared_tool])
    rows=AppsToolsProjection(registry,Integrations([])).tools_list()
    assert any(row['tool_id']=='prepared_tool' for row in rows)
    assert prepared['count']==0
