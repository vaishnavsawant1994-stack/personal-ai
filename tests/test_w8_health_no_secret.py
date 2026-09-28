from types import SimpleNamespace
from models.governed_router import GovernedModelRouter


def test_health_status_never_exposes_api_key_or_url_credentials():
    s=SimpleNamespace(ai_provider='local',cloud_runtime_enabled=False,hosted_runtime=False,local_ai_explicit=True,local_ai_url='',local_ai_model='',self_hosted_ai_url='https://owner:pw@local.test/v1?token=q',self_hosted_ai_api_key='KEYSECRET',self_hosted_ai_model='m',model_fallback_providers=(),model_disabled_providers=(),model_request_timeout_seconds=1,model_health_timeout_seconds=.5,model_retry_attempts=0,model_retry_backoff_seconds=0,model_max_failovers=0,model_local_first=True,allow_external_for_sensitive=False,openrouter_api_key='',openrouter_model='',openai_api_key='',openai_base_url='',openai_model='',gemini_api_key='',gemini_base_url='',gemini_model='',embedding_model='e')
    text=repr(GovernedModelRouter(s).status())
    assert 'KEYSECRET' not in text and 'owner' not in text and 'pw' not in text and 'token=q' not in text
    assert 'local.test' in text
