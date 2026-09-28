from types import SimpleNamespace
import pytest
import requests
from models.governed_router import GovernedModelRouter
from models.router import ModelAuthenticationError, ModelUnavailable


def settings(**overrides):
    values={'ai_provider':'local','cloud_runtime_enabled':False,'hosted_runtime':False,'local_ai_explicit':True,'local_ai_url':'https://local.test/v1','local_ai_model':'local-model','self_hosted_ai_url':'https://local.test/v1','self_hosted_ai_api_key':'','self_hosted_ai_model':'local-model','model_fallback_providers':('openai',),'model_disabled_providers':(),'model_request_timeout_seconds':1,'model_health_timeout_seconds':.5,'model_retry_attempts':1,'model_retry_backoff_seconds':0,'model_max_failovers':2,'model_local_first':True,'allow_external_for_sensitive':False,'openrouter_api_key':'','openrouter_model':'or','openai_api_key':'secret','openai_base_url':'https://cloud.test/v1','openai_model':'cloud-model','gemini_api_key':'','gemini_base_url':'https://gemini.test/v1','gemini_model':'gemini','embedding_model':'embed'}
    values.update(overrides);return SimpleNamespace(**values)

class Response:
    def __init__(self,status_code=200,payload=None):self.status_code=status_code;self.payload=payload or {'choices':[{'message':{'content':'ok'}}]};self.content=b''
    def json(self):return self.payload


def test_transient_failure_retries_then_succeeds(monkeypatch):
    calls=[]
    def request(*args,**kwargs):
        calls.append(args[1]);
        if len(calls)==1:raise requests.Timeout('slow')
        return Response()
    monkeypatch.setattr(requests,'request',request);router=GovernedModelRouter(settings())
    assert router.chat('hello')=='ok';assert len(calls)==2
    assert router.status()['w8']['counters']['retries']==1


def test_permanent_auth_failure_does_not_retry_primary(monkeypatch):
    calls=[]
    def request(method,url,**kwargs):calls.append(url);return Response(status_code=401) if url.startswith('https://local') else Response()
    monkeypatch.setattr(requests,'request',request);router=GovernedModelRouter(settings())
    assert router.chat('hello')=='ok'
    assert calls.count('https://local.test/v1/chat/completions')==1


def test_sensitive_task_cannot_escape_to_external_provider(monkeypatch):
    calls=[]
    def request(method,url,**kwargs):calls.append(url);raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests,'request',request);router=GovernedModelRouter(settings())
    with pytest.raises(ModelUnavailable):router.chat('secret',sensitivity='sensitive')
    assert all(url.startswith('https://local') for url in calls)


def test_owner_disabled_provider_is_not_routed(monkeypatch):
    calls=[]
    monkeypatch.setattr(requests,'request',lambda method,url,**kwargs:(calls.append(url) or Response()))
    router=GovernedModelRouter(settings(model_disabled_providers=('self_hosted',),ai_provider='openai',model_local_first=False))
    assert router.chat('hello')=='ok';assert calls==['https://cloud.test/v1/chat/completions']


def test_failover_budget_and_attempted_targets_are_bounded(monkeypatch):
    calls=[]
    def request(method,url,**kwargs):calls.append(url);raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests,'request',request)
    router=GovernedModelRouter(settings(model_fallback_providers=('openai','openrouter','gemini'),openrouter_api_key='x',gemini_api_key='x',model_retry_attempts=0,model_max_failovers=1))
    with pytest.raises(ModelUnavailable):router.chat('hello')
    assert len(calls)==2
    row=router.status()['w8']['recent_generations'][-1]
    assert len(row['attempted_targets'])==2


def test_malformed_response_is_not_blindly_retried(monkeypatch):
    calls=[]
    def request(method,url,**kwargs):calls.append(url);return Response(payload={'choices':[]}) if url.startswith('https://local') else Response()
    monkeypatch.setattr(requests,'request',request);router=GovernedModelRouter(settings())
    assert router.chat('hello')=='ok';assert calls.count('https://local.test/v1/chat/completions')==1


def test_health_probe_is_bounded_and_does_not_send_prompt(monkeypatch):
    seen=[]
    def request(method,url,**kwargs):seen.append((method,url,kwargs));return Response(payload={'data':[]})
    monkeypatch.setattr(requests,'request',request);router=GovernedModelRouter(settings())
    status=router.health_status(probe=True)
    assert status['w8']['providers']['self_hosted']['state']=='healthy'
    assert all(item[0]=='GET' and item[1].endswith('/models') for item in seen)
    assert all('json' not in item[2] for item in seen)


def test_generation_observability_never_contains_prompt_or_key(monkeypatch):
    monkeypatch.setattr(requests,'request',lambda *args,**kwargs:Response())
    router=GovernedModelRouter(settings());router.chat('TOP SECRET PROMPT')
    text=repr(router.status())
    assert 'TOP SECRET PROMPT' not in text and 'secret' not in text
