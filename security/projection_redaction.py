from __future__ import annotations

import re
from typing import Any

# Narrow credential-context redaction for externally influenced owner-facing text.
# Ordinary long identifiers are preserved unless they occur in a credential structure.
_AUTHORIZATION = re.compile(r'(?i)(authorization\s*:\s*)(?:(?:bearer|basic)\s+)?([^\s,;]+)')
_BEARER = re.compile(r'(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{8,})')
_NAMED_SECRET = re.compile(
    r'(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|credential|session[_-]?(?:token|secret))\b(\s*[:=]\s*)(["\']?)([^\s&;,"\']+)(["\']?)'
)
_COOKIE = re.compile(r'(?i)\b(set-cookie|cookie)\s*:\s*([^\r\n;]+(?:;[^\r\n]*)?)')
_URL_SECRET = re.compile(r'(?i)([?&](?:token|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|session[_-]?(?:token|secret)|key)=)([^&#\s]+)')
_PRIVATE_KEY = re.compile(r'(?is)-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----')


def sanitize_sensitive_text(value: str) -> str:
    text = str(value)
    text = _PRIVATE_KEY.sub('[redacted private key]', text)
    text = _AUTHORIZATION.sub(lambda m: f'{m.group(1)}[redacted]', text)
    text = _BEARER.sub('[redacted bearer token]', text)
    text = _NAMED_SECRET.sub(lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}[redacted]{m.group(5)}', text)
    text = _COOKIE.sub(lambda m: f'{m.group(1)}: [redacted]', text)
    text = _URL_SECRET.sub(lambda m: f'{m.group(1)}[redacted]', text)
    return text


def sanitize_external_value(value: Any, *, depth: int = 0):
    if depth > 12:
        return '[bounded]'
    if isinstance(value, dict):
        return {key: sanitize_external_value(item, depth=depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, list):
        return [sanitize_external_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(sanitize_external_value(item, depth=depth + 1) for item in value[:100])
    if isinstance(value, str):
        return sanitize_sensitive_text(value[:8000])
    return value
