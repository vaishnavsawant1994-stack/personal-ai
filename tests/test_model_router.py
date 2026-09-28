from types import SimpleNamespace

import pytest
import requests

from models.router import (
    InvalidModelResponse,
    ModelAuthenticationError,
    ModelCreditsExhausted,
    ModelRouter,
    ModelSpendLimitReached,
    ModelTimeout,
    ModelUnavailable,
)


def settings(**overrides):
    values = {
        'ai_provider': 'local',
        'cloud_runtime_enabled': True,
        'hosted_runtime': False,
        'local_ai_explicit': False,
        'local_ai_url': 'http://127.0.0.1:11434/v1',
        'local_ai_model': 'llama3.2',
        'self_hosted_ai_url': '',
        'self_hosted_ai_api_key': '',
        'self_hosted_ai_model': 'owner-model',
        'model_fallback_providers': (),
        'model_request_timeout_seconds': 2,
        'model_health_timeout_seconds': 1,
        'allow_external_for_sensitive': False,
        'openrouter_api_key': '',
        'openrouter_model': 'remote-model',
        'openai_api_key': '',
        'openai_base_url': 'https://api.openai.com/v1',
        'openai_model': 'cloud-model',
        'gemini_api_key': '',
        'gemini_base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'gemini_model': 'gemini-3.5-flash-lite',
        'embedding_model': 'embed-model',
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class Response:
    def __init__(self, status_code=200, payload=None, content=b''):
        self.status_code = status_code
        self.payload = payload or {}
        self.content = content

    def json(self):
        return self.payload


def test_cloud_runtime_does_not_silently_call_loopback(monkeypatch):
    called = False

    def request(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings())
    assert router.status()['state'] == 'not_configured'
    with pytest.raises(ModelUnavailable):
        router.chat('hello')
    assert called is False


def test_railway_runtime_does_not_treat_loopback_as_a_model(monkeypatch):
    called = False

    def request(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(cloud_runtime_enabled=False, hosted_runtime=True))
    assert router.status()['state'] == 'not_configured'
    assert router.status()['provider']['endpoint_host'] == ''
    with pytest.raises(ModelUnavailable):
        router.chat('hello')
    assert called is False


def test_public_status_does_not_expose_endpoint_credentials():
    router = ModelRouter(settings(
        self_hosted_ai_url='https://owner:password@gpu.example/v1?token=secret',
        self_hosted_ai_api_key='api-secret',
    ))
    serialized = repr(router.status())
    assert 'gpu.example' in serialized
    assert 'password' not in serialized
    assert 'token=secret' not in serialized
    assert 'api-secret' not in serialized


def test_public_status_exposes_privacy_policy_without_secrets():
    router = ModelRouter(settings(allow_external_for_sensitive=False))

    assert router.status()['external_sensitive_allowed'] is False


def test_unknown_provider_value_is_never_exposed():
    secret_like_value = 'sk-proj-do-not-expose-this-value'
    router = ModelRouter(settings(ai_provider=secret_like_value))

    status = router.status()
    serialized = repr(status)

    assert secret_like_value not in serialized
    assert status['primary_provider'] == 'invalid'
    assert status['state'] == 'not_configured'


def test_self_hosted_openai_compatible_endpoint_is_used(monkeypatch):
    seen = {}

    def request(method, url, **kwargs):
        seen.update(method=method, url=url, headers=kwargs['headers'], payload=kwargs['json'])
        return Response(payload={'choices': [{'message': {'content': 'owner-controlled reply'}}]})

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(self_hosted_ai_url='https://gpu.example/v1'))
    assert router.chat('hello') == 'owner-controlled reply'
    assert seen['url'] == 'https://gpu.example/v1/chat/completions'
    assert 'Authorization' not in seen['headers']


def test_gemini_openai_compatible_endpoint_is_used(monkeypatch):
    seen = {}

    def request(method, url, **kwargs):
        seen.update(method=method, url=url, headers=kwargs['headers'], payload=kwargs['json'])
        return Response(payload={'choices': [{'message': {'content': 'four'}}]})

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(ai_provider='gemini', gemini_api_key='gemini-secret'))

    assert router.chat('What is 2+2?') == 'four'
    assert seen['url'] == 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
    assert seen['headers']['Authorization'] == 'Bearer gemini-secret'
    assert seen['payload']['model'] == 'gemini-3.5-flash-lite'
    assert 'gemini-secret' not in repr(router.status())


def test_allowed_fallback_is_recorded(monkeypatch):
    events = []
    audit = []

    class Events:
        def emit(self, name, **payload):
            events.append((name, payload))

    def request(method, url, **kwargs):
        if url.startswith('https://gpu.example'):
            raise requests.ConnectionError('offline')
        return Response(payload={'choices': [{'message': {'content': 'fallback reply'}}]})

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(
        settings(
            self_hosted_ai_url='https://gpu.example/v1',
            openrouter_api_key='secret',
            model_fallback_providers=('openrouter',),
        ),
        events=Events(),
        audit=lambda *args: audit.append(args),
    )
    assert router.chat('hello') == 'fallback reply'
    assert any(name == 'model.fallback' and payload['provider'] == 'openrouter' for name, payload in events)
    assert any(item[1] == 'fallback' for item in audit)
    assert all('secret' not in repr(item) for item in audit)


@pytest.mark.parametrize(
    ('effect', 'expected'),
    [
        (requests.Timeout('slow'), ModelTimeout),
        (requests.ConnectionError('offline'), ModelUnavailable),
    ],
)
def test_transport_failures_have_typed_errors(monkeypatch, effect, expected):
    def request(*args, **kwargs):
        raise effect

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(self_hosted_ai_url='https://gpu.example/v1'))
    with pytest.raises(expected):
        router.chat('hello')


def test_authentication_and_invalid_payload_are_distinct(monkeypatch):
    monkeypatch.setattr(requests, 'request', lambda *args, **kwargs: Response(status_code=401))
    router = ModelRouter(settings(self_hosted_ai_url='https://gpu.example/v1'))
    with pytest.raises(ModelAuthenticationError):
        router.chat('hello')

    monkeypatch.setattr(requests, 'request', lambda *args, **kwargs: Response(payload={'choices': []}))
    with pytest.raises(InvalidModelResponse):
        router.chat('hello')


@pytest.mark.parametrize(
    ('provider_code', 'expected'),
    [
        ('credit_balance_exhausted', ModelCreditsExhausted),
        ('project_spend_limit_exceeded', ModelSpendLimitReached),
        ('organization_spend_limit_exceeded', ModelSpendLimitReached),
        ('organization_usage_limit_exceeded', ModelSpendLimitReached),
    ],
)
def test_billing_429_is_distinct_from_temporary_rate_limit(monkeypatch, provider_code, expected):
    monkeypatch.setattr(
        requests,
        'request',
        lambda *args, **kwargs: Response(
            status_code=429,
            payload={'error': {'code': provider_code, 'message': 'must never be retained'}},
        ),
    )
    router = ModelRouter(settings(self_hosted_ai_url='https://gpu.example/v1'))

    with pytest.raises(expected):
        router.chat('hello')


def test_sensitive_content_cannot_fall_back_to_external_provider(monkeypatch):
    called = []

    def request(method, url, **kwargs):
        called.append(url)
        raise requests.ConnectionError('private model offline')

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(
        self_hosted_ai_url='https://gpu.example/v1',
        openrouter_api_key='secret',
        model_fallback_providers=('openrouter',),
    ))
    with pytest.raises(ModelUnavailable):
        router.chat('private fact', sensitivity='sensitive')
    assert called == ['https://gpu.example/v1/chat/completions']


def test_model_provider_response_body_is_streamed_and_bounded(monkeypatch):
    seen = {}

    class StreamingResponse:
        status_code = 200
        headers = {}

        def __init__(self):
            self.closed = False

        def iter_content(self, chunk_size=65536):
            yield b'x' * 40000
            yield b'y' * 40000

        def close(self):
            self.closed = True

    response = StreamingResponse()

    def request(*args, **kwargs):
        seen['stream'] = kwargs.get('stream')
        return response

    monkeypatch.setattr(requests, 'request', request)
    router = ModelRouter(settings(
        self_hosted_ai_url='https://gpu.example/v1',
        model_max_response_bytes=65536,
    ))

    with pytest.raises(InvalidModelResponse, match='size limit'):
        router.chat('hello')

    assert seen['stream'] is True
    assert response.closed is True
