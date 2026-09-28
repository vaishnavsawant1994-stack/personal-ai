import requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter


def test_failover_audit_contains_reason_but_not_prompt(monkeypatch):
    events=[]
    class E:
        def emit(self,name,**payload):events.append((name,payload))
    class R:
        status_code=200;content=b''
        def json(self):return {'choices':[{'message':{'content':'ok'}}]}
    def req(method,url,**kwargs):
        if 'local' in url:raise requests.ConnectionError('offline')
        return R()
    monkeypatch.setattr(requests,'request',req)
    s=SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=('openai',),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=1,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='x',openai_base_url='https://cloud.test/v1',openai_model='m2',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    r=GovernedModelRouter(s,events=E());assert r.chat('PRIVATE PROMPT')=='ok'
    assert any(name=='model.fallback' and payload['reason']=='prior_target_failed' for name,payload in events)
    assert 'PRIVATE PROMPT' not in repr(events)
