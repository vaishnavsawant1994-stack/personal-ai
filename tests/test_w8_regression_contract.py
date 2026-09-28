from types import SimpleNamespace
import requests
from models.router import ModelRouter
from models.governed_router import GovernedModelRouter


def base_settings(**overrides):
    d=dict(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='https://local.test/v1',local_ai_model='m',self_hosted_ai_url='https://local.test/v1',self_hosted_ai_api_key='',self_hosted_ai_model='m',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='',openai_base_url='https://cloud.test/v1',openai_model='',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e');d.update(overrides);return SimpleNamespace(**d)

class Response:
    status_code=200;content=b''
    def json(self):return {'choices':[{'message':{'content':'same'}}]}


def test_governed_router_is_subclass_of_existing_router():
    assert issubclass(GovernedModelRouter,ModelRouter)


def test_existing_chat_contract_is_preserved(monkeypatch):
    monkeypatch.setattr(requests,'request',lambda *a,**k:Response())
    assert GovernedModelRouter(base_settings()).chat('hello')=='same'


def test_status_keeps_existing_top_level_contract():
    status=GovernedModelRouter(base_settings()).status()
    for key in ('state','primary_provider','fallback_providers','local_first','external_sensitive_allowed','provider','providers','last_check'):
        assert key in status
    assert 'w8' in status
