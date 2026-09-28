from __future__ import annotations

from dataclasses import asdict, dataclass
import io
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import requests


class ModelError(RuntimeError):
    code = 'provider_error'
    status_code = 502
    user_message = 'The AI model returned an error. Please try again.'

    def __init__(self, message: str = '', *, provider: str | None = None):
        super().__init__(message or self.user_message)
        self.provider = provider


class ModelUnavailable(ModelError):
    code = 'model_unavailable'
    status_code = 503
    user_message = 'The AI model is currently unavailable. Please try again shortly.'


class ModelAuthenticationError(ModelError):
    code = 'model_authentication_failed'
    status_code = 503
    user_message = 'The AI model connection needs administrator attention.'


class ModelRateLimited(ModelError):
    code = 'model_rate_limited'
    status_code = 429
    user_message = 'The AI model is temporarily busy. Please try again shortly.'


class ModelCreditsExhausted(ModelError):
    code = 'model_credits_exhausted'
    status_code = 503
    user_message = 'The AI provider has no remaining API credit. Add billing credits and try again.'


class ModelSpendLimitReached(ModelError):
    code = 'model_spend_limit_reached'
    status_code = 503
    user_message = 'The AI provider spending limit has been reached. Update the provider limit and try again.'


class ModelTimeout(ModelError):
    code = 'model_timeout'
    status_code = 504
    user_message = 'The AI model took too long to respond. Please try again.'


class InvalidModelResponse(ModelError):
    code = 'invalid_model_response'
    status_code = 502
    user_message = 'The AI model returned an invalid response. Please try again.'


@dataclass(frozen=True)
class Provider:
    id: str
    base_url: str
    api_key: str
    model: str
    private: bool
    capabilities: tuple[str, ...]
    cost_rank: int
    latency_rank: int

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def public(self) -> dict:
        data = asdict(self)
        data.pop('api_key', None)
        base_url = data.pop('base_url', '')
        parsed = urlsplit(base_url)
        data['endpoint_host'] = parsed.hostname or ''
        data['configured'] = self.configured
        return data


class ModelRouter:
    """Replaceable, OpenAI-compatible routing with explicit safe failures."""

    def __init__(self, settings, *, events=None, audit=None):
        self.settings = settings
        self.events = events
        self.audit = audit
        self.timeout = max(1.0, float(getattr(settings, 'model_request_timeout_seconds', 120)))
        self.health_timeout = max(0.5, float(getattr(settings, 'model_health_timeout_seconds', 5)))
        self.max_response_bytes = max(
            64 * 1024,
            min(64 * 1024 * 1024, int(getattr(settings, 'model_max_response_bytes', 32 * 1024 * 1024))),
        )
        self.allow_external_sensitive = bool(getattr(settings, 'allow_external_for_sensitive', False))
        self.local_first = bool(getattr(settings, 'model_local_first', True))
        self.providers = self._build_providers()
        selected = str(getattr(settings, 'ai_provider', 'local') or 'local').strip().lower()
        self.primary = self._safe_provider_id(selected)
        fallback = getattr(settings, 'model_fallback_providers', ()) or ()
        if isinstance(fallback, str):
            fallback = tuple(item.strip() for item in fallback.split(',') if item.strip())
        self.fallbacks = tuple(
            provider_id
            for item in fallback
            if (provider_id := self._safe_provider_id(str(item).strip().lower())) != 'invalid'
        )
        self._last = {'state': 'not_checked', 'provider': self.primary, 'checked_at': None, 'error_code': None}
        self._health = {
            provider_id: {'state': 'not_checked', 'error_code': None, 'checked_at': None, 'latency_ms': None}
            for provider_id in self.providers
        }

    def _safe_provider_id(self, value: str) -> str:
        """Normalize provider IDs without retaining arbitrary secret-like input."""
        if value in {'local', 'self-hosted', 'self_hosted'}:
            return 'self_hosted'
        if value in self.providers:
            return value
        return 'invalid'

    def _build_providers(self) -> dict[str, Provider]:
        explicit_local = bool(getattr(self.settings, 'local_ai_explicit', False))
        hosted = bool(
            getattr(self.settings, 'cloud_runtime_enabled', False)
            or getattr(self.settings, 'hosted_runtime', False)
        )
        self_hosted_url = str(getattr(self.settings, 'self_hosted_ai_url', '') or '').rstrip('/')
        if not self_hosted_url and (explicit_local or not hosted):
            self_hosted_url = str(getattr(self.settings, 'local_ai_url', '') or '').rstrip('/')
        self_hosted_model = str(
            getattr(self.settings, 'self_hosted_ai_model', '')
            or getattr(self.settings, 'local_ai_model', '')
        )
        return {
            'self_hosted': Provider(
                'self_hosted', self_hosted_url,
                str(getattr(self.settings, 'self_hosted_ai_api_key', '') or ''),
                self_hosted_model, True, ('chat', 'json', 'vision', 'embedding', 'audio'), 2, 2,
            ),
            'openrouter': Provider(
                'openrouter', 'https://openrouter.ai/api/v1',
                str(getattr(self.settings, 'openrouter_api_key', '') or ''),
                str(getattr(self.settings, 'openrouter_model', '') or ''),
                False, ('chat', 'json', 'vision'), 2, 3,
            ),
            'openai': Provider(
                'openai', str(getattr(self.settings, 'openai_base_url', 'https://api.openai.com/v1')).rstrip('/'),
                str(getattr(self.settings, 'openai_api_key', '') or ''),
                str(getattr(self.settings, 'openai_model', '') or ''),
                False, ('chat', 'json', 'vision', 'embedding', 'audio'), 4, 2,
            ),
            'gemini': Provider(
                'gemini', str(getattr(
                    self.settings,
                    'gemini_base_url',
                    'https://generativelanguage.googleapis.com/v1beta/openai',
                )).rstrip('/'),
                str(getattr(self.settings, 'gemini_api_key', '') or ''),
                str(getattr(self.settings, 'gemini_model', '') or ''),
                False, ('chat', 'json', 'vision'), 1, 1,
            ),
        }

    def _candidates(self, capability: str, sensitivity: str) -> list[Provider]:
        candidates = []
        provider_order = [self.primary, *self.fallbacks]
        local = self.providers.get('self_hosted')
        if self.local_first and local and local.configured:
            provider_order.insert(0, 'self_hosted')
        for provider_id in provider_order:
            provider = self.providers.get(provider_id)
            if not provider or provider in candidates or capability not in provider.capabilities:
                continue
            if sensitivity in {'sensitive', 'secret'} and not provider.private and not self.allow_external_sensitive:
                continue
            candidates.append(provider)
        return candidates

    def _record(self, event: str, **payload):
        safe = {key: value for key, value in payload.items() if key not in {'prompt', 'messages', 'api_key'}}
        if self.events:
            self.events.emit(event, **safe)
        if self.audit:
            self.audit('model', event.removeprefix('model.'), safe)

    def _run(self, capability: str, call, *, sensitivity: str = 'internal'):
        candidates = self._candidates(capability, sensitivity)
        if not candidates:
            self._last = {'state': 'unavailable', 'provider': self.primary, 'checked_at': time.time(), 'error_code': 'model_not_configured'}
            raise ModelUnavailable('No allowed model provider is configured', provider=self.primary)
        last_error = None
        for index, provider in enumerate(candidates):
            if not provider.configured or (not provider.private and not provider.api_key):
                last_error = ModelUnavailable('Provider is not configured', provider=provider.id)
                continue
            try:
                started = time.perf_counter()
                result = call(provider)
                latency_ms = round((time.perf_counter() - started) * 1000, 3)
                self._last = {'state': 'available', 'provider': provider.id, 'checked_at': time.time(), 'error_code': None}
                self._health[provider.id] = {'state': 'available', 'error_code': None, 'checked_at': time.time(), 'latency_ms': latency_ms}
                self._record('model.selected', provider=provider.id, model=provider.model, capability=capability, fallback=index > 0)
                if index:
                    self._record('model.fallback', provider=provider.id, model=provider.model, capability=capability)
                return result
            except ModelError as exc:
                last_error = exc
                self._last = {'state': 'unavailable', 'provider': provider.id, 'checked_at': time.time(), 'error_code': exc.code}
                self._health[provider.id] = {'state': 'unavailable', 'error_code': exc.code, 'checked_at': time.time(), 'latency_ms': None}
                self._record('model.error', provider=provider.id, capability=capability, error_code=exc.code)
        raise last_error or ModelUnavailable(provider=self.primary)

    def chat(self, prompt: str, *, system: str = 'You are a helpful personal AI assistant.', history: list[dict] | None = None, temperature: float = .3, sensitivity: str = 'internal') -> str:
        messages = [{'role': 'system', 'content': system}, *(history or []), {'role': 'user', 'content': prompt}]
        return self._run('chat', lambda provider: self._chat_call(provider, messages, temperature), sensitivity=sensitivity)

    def json(self, prompt: str, *, system: str = 'Return valid JSON only.', sensitivity: str = 'internal') -> dict:
        raw = self.chat(prompt, system=system, temperature=.1, sensitivity=sensitivity).strip()
        if raw.startswith('```'):
            raw = raw.replace('```json', '').replace('```', '').strip()
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidModelResponse('Model did not return valid JSON', provider=self._last.get('provider')) from exc
        if not isinstance(value, dict):
            raise InvalidModelResponse('Model JSON response must be an object', provider=self._last.get('provider'))
        return value

    def vision(self, prompt: str, image_data_url: str) -> str:
        messages = [{'role': 'user', 'content': [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {'url': image_data_url}}]}]
        return self._run('vision', lambda provider: self._chat_call(provider, messages, .1))

    def embed(self, text: str) -> list[float]:
        def call(provider):
            model = str(getattr(self.settings, 'embedding_model', '') or provider.model)
            response = self._request(provider, 'POST', '/embeddings', json={'model': model, 'input': text})
            try:
                return list(map(float, response.json()['data'][0]['embedding']))
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise InvalidModelResponse('Invalid embedding response', provider=provider.id) from exc
        return self._run('embedding', call)

    def transcribe(self, path: Path) -> str:
        def call(provider):
            model = str(getattr(self.settings, 'stt_model', 'whisper-1'))
            with open(path, 'rb') as handle:
                response = self._request(provider, 'POST', '/audio/transcriptions', files={'file': (Path(path).name, handle, 'audio/wav')}, data={'model': model})
            try:
                return str(response.json().get('text', '')).strip()
            except (AttributeError, ValueError, json.JSONDecodeError) as exc:
                raise InvalidModelResponse('Invalid transcription response', provider=provider.id) from exc
        return self._run('audio', call)

    def synthesize(self, text: str) -> bytes:
        def call(provider):
            payload = {'model': str(getattr(self.settings, 'tts_model', 'tts-1')), 'voice': str(getattr(self.settings, 'tts_voice', 'alloy')), 'input': text, 'format': 'wav'}
            return self._request(provider, 'POST', '/audio/speech', json=payload).content
        return self._run('audio', call)

    def speak(self, text: str):
        try:
            import sounddevice as sd
            import soundfile as sf
            audio, sample_rate = sf.read(io.BytesIO(self.synthesize(text)), dtype='float32')
            sd.play(audio, sample_rate)
            sd.wait()
            return
        except Exception:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()

    def status(self, *, probe: bool = False) -> dict:
        provider = self.providers.get(self.primary)
        configured = bool(provider and provider.configured and (provider.private or provider.api_key))
        result = {
            'state': 'configured' if configured else 'not_configured',
            'primary_provider': self.primary,
            'fallback_providers': list(self.fallbacks),
            'local_first': self.local_first,
            'external_sensitive_allowed': self.allow_external_sensitive,
            'provider': provider.public() if provider else None,
            'providers': [
                {**item.public(), 'health': dict(self._health[item.id])}
                for item in self.providers.values()
            ],
            'last_check': dict(self._last),
        }
        if not probe or not configured:
            return result
        try:
            self._request(provider, 'GET', '/models', timeout=self.health_timeout)
            result['state'] = 'available'
            self._last = {'state': 'available', 'provider': provider.id, 'checked_at': time.time(), 'error_code': None}
            self._health[provider.id] = {'state': 'available', 'error_code': None, 'checked_at': time.time(), 'latency_ms': None}
        except ModelError as exc:
            result['state'] = 'unavailable'
            result['error_code'] = exc.code
            self._last = {'state': 'unavailable', 'provider': provider.id, 'checked_at': time.time(), 'error_code': exc.code}
            self._health[provider.id] = {'state': 'unavailable', 'error_code': exc.code, 'checked_at': time.time(), 'latency_ms': None}
        result['last_check'] = dict(self._last)
        return result

    def _chat_call(self, provider: Provider, messages, temperature):
        response = self._request(provider, 'POST', '/chat/completions', json={'model': provider.model, 'messages': messages, 'temperature': temperature})
        try:
            content = response.json()['choices'][0]['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('empty content')
            return content.strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidModelResponse('Invalid chat completion response', provider=provider.id) from exc

    @staticmethod
    def _close_response(response) -> None:
        close = getattr(response, 'close', None)
        if callable(close):
            close()

    def _bounded_response(self, response, provider: Provider):
        limit = self.max_response_bytes
        headers = getattr(response, 'headers', None)
        if headers is not None:
            raw_length = headers.get('Content-Length') or headers.get('content-length')
            if raw_length:
                try:
                    if int(raw_length) > limit:
                        self._close_response(response)
                        raise InvalidModelResponse('Model provider response exceeded the configured size limit', provider=provider.id)
                except ValueError:
                    pass

        iterator = getattr(response, 'iter_content', None)
        if not callable(iterator):
            content = getattr(response, 'content', b'') or b''
            if len(content) > limit:
                self._close_response(response)
                raise InvalidModelResponse('Model provider response exceeded the configured size limit', provider=provider.id)
            return response

        chunks = []
        total = 0
        try:
            for chunk in iterator(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > limit:
                    raise InvalidModelResponse('Model provider response exceeded the configured size limit', provider=provider.id)
                chunks.append(chunk)
        except requests.Timeout as exc:
            raise ModelTimeout(provider=provider.id) from exc
        except requests.ConnectionError as exc:
            raise ModelUnavailable(provider=provider.id) from exc
        except requests.RequestException as exc:
            raise ModelError(provider=provider.id) from exc
        finally:
            self._close_response(response)

        response._content = b''.join(chunks)
        response._content_consumed = True
        return response

    def _request(self, provider: Provider, method: str, path: str, *, timeout: float | None = None, **kwargs):
        headers = dict(kwargs.pop('headers', {}) or {})
        kwargs.pop('stream', None)
        if 'json' in kwargs:
            headers.setdefault('Content-Type', 'application/json')
        if provider.api_key:
            headers['Authorization'] = f'Bearer {provider.api_key}'
        try:
            response = requests.request(
                method,
                f'{provider.base_url}{path}',
                headers=headers,
                timeout=timeout or self.timeout,
                stream=True,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ModelTimeout(provider=provider.id) from exc
        except requests.ConnectionError as exc:
            raise ModelUnavailable(provider=provider.id) from exc
        except requests.RequestException as exc:
            raise ModelError(provider=provider.id) from exc
        if response.status_code in {401, 403}:
            self._close_response(response)
            raise ModelAuthenticationError(provider=provider.id)
        if response.status_code == 429:
            response = self._bounded_response(response, provider)
            error_code = self._response_error_code(response)
            if error_code == 'credit_balance_exhausted':
                raise ModelCreditsExhausted(provider=provider.id)
            if error_code in {
                'organization_spend_limit_exceeded',
                'project_spend_limit_exceeded',
                'organization_usage_limit_exceeded',
            }:
                raise ModelSpendLimitReached(provider=provider.id)
            raise ModelRateLimited(provider=provider.id)
        if response.status_code in {408, 504}:
            self._close_response(response)
            raise ModelTimeout(provider=provider.id)
        if response.status_code >= 500:
            self._close_response(response)
            raise ModelUnavailable(provider=provider.id)
        if response.status_code >= 400:
            self._close_response(response)
            raise ModelError(f'Provider returned HTTP {response.status_code}', provider=provider.id)
        return self._bounded_response(response, provider)

    @staticmethod
    def _response_error_code(response) -> str:
        """Extract only a documented provider error code; never retain its message/body."""
        try:
            payload = response.json()
        except (AttributeError, TypeError, ValueError):
            return ''
        error = payload.get('error') if isinstance(payload, dict) else None
        code = error.get('code') if isinstance(error, dict) else None
        return str(code or '').strip().lower()
