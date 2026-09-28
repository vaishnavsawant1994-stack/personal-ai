import pytest,requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter
from models.router import ModelError


def s():return SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='',openai_base_url='',openai_model='',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')

@pytest.mark.parametrize('effect',[requests.ConnectionError('connection refused'),requests.ConnectionError('dns failure'),requests.Timeout('delayed response'),requests.RequestException('network abstraction')])
def test_deterministic_transport_failure_injection(monkeypatch,effect):
    monkeypatch.setattr(requests,'request',lambda *a,**k:(_ for _ in ()).throw(effect));r=GovernedModelRouter(s())
    with pytest.raises(ModelError):r.chat('x')
    assert r.status()['w8']['counters']['failures']==1
