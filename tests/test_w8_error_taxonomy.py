import pytest
import requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter
from models.router import ModelAuthenticationError,ModelRateLimited,ModelTimeout,ModelUnavailable,ModelError


def settings():
    return SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='',openai_base_url='https://cloud.test/v1',openai_model='',gemini_api_key='',gemini_base_url='https://g.test/v1',gemini_model='',embedding_model='e')

class Response:
    def __init__(self,status,payload=None):self.status_code=status;self.payload=payload or {};self.content=b''
    def json(self):return self.payload

@pytest.mark.parametrize('effect,expected,code',[
    (requests.Timeout('x'),ModelTimeout,'timeout'),
    (requests.ConnectionError('x'),ModelUnavailable,'provider_unavailable'),
])
def test_transport_taxonomy(monkeypatch,effect,expected,code):
    monkeypatch.setattr(requests,'request',lambda *a,**k:(_ for _ in ()).throw(effect));r=GovernedModelRouter(settings())
    with pytest.raises(expected):r.chat('x')
    assert r.status()['w8']['recent_generations'][-1]['error_code']==code

@pytest.mark.parametrize('status,expected,code',[(401,ModelAuthenticationError,'authentication_error'),(429,ModelRateLimited,'rate_limited'),(503,ModelUnavailable,'provider_unavailable'),(400,ModelError,'unknown_failure')])
def test_http_taxonomy(monkeypatch,status,expected,code):
    monkeypatch.setattr(requests,'request',lambda *a,**k:Response(status));r=GovernedModelRouter(settings())
    with pytest.raises(expected):r.chat('x')
    assert r.status()['w8']['recent_generations'][-1]['error_code']==code
