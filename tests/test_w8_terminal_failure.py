import pytest,requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter
from models.router import ModelUnavailable

def test_all_candidates_exhaust_to_truthful_controlled_failure(monkeypatch):
    monkeypatch.setattr(requests,'request',lambda *a,**k:(_ for _ in ()).throw(requests.ConnectionError('down')))
    s=SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=('openai',),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=1,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='x',openai_base_url='https://cloud.test/v1',openai_model='m2',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    r=GovernedModelRouter(s)
    with pytest.raises(ModelUnavailable):r.chat('x')
    row=r.status()['w8']['recent_generations'][-1];assert row['result']=='failed' and row['routing_reason']=='exhausted'
