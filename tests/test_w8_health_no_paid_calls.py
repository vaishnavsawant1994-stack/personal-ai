from types import SimpleNamespace
from models.governed_router import GovernedModelRouter


def test_status_without_probe_never_calls_provider(monkeypatch):
    called=[];monkeypatch.setattr('requests.request',lambda *a,**k:called.append((a,k)))
    s=SimpleNamespace(ai_provider='openai',cloud_runtime_enabled=True,hosted_runtime=True,local_ai_explicit=False,local_ai_url='',local_ai_model='',self_hosted_ai_url='',self_hosted_ai_api_key='',self_hosted_ai_model='',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=False,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='configured-not-used',openai_base_url='https://cloud.test/v1',openai_model='m',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    r=GovernedModelRouter(s);status=r.status(probe=False)
    assert status['w8']['providers']['openai']['configuration']=='configured'
    assert status['w8']['providers']['openai']['state']=='unknown'
    assert called==[]
