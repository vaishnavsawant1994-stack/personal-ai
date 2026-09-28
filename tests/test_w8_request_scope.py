import requests
from types import SimpleNamespace
from models.governed_router import GovernedModelRouter


def test_failover_attempt_history_is_request_scoped(monkeypatch):
    class R:
        status_code=200;content=b''
        def json(self):return {'choices':[{'message':{'content':'ok'}}]}
    monkeypatch.setattr(requests,'request',lambda *a,**k:R())
    s=SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='',openai_base_url='',openai_model='',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    r=GovernedModelRouter(s);r.chat('one');r.chat('two');rows=r.status()['w8']['recent_generations'][-2:]
    assert rows[0]['generation_id']!=rows[1]['generation_id']
    assert rows[0]['attempted_targets']==['self_hosted']==rows[1]['attempted_targets']
