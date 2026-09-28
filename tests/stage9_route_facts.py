"""Derive Stage 9 route facts from production handlers.

The JSON record must match this derivation. A missing auth check stays a gap
or unproven. It is not marked canonical.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = {
    ('POST', '/iphone/api/voice/turn'),
    ('POST', '/iphone/api/voice/barge'),
    ('POST', '/iphone/api/voice/client-event'),
    ('POST', '/iphone/api/approval/{approval_id}/approve'),
    ('POST', '/iphone/api/approval/{approval_id}/reject'),
    ('GET', '/iphone/api/conversations'),
    ('GET', '/iphone/api/conversations/{conversation_id}'),
}
AUTH_NAMES = (
    'authenticate',
    'auth_device',
    'cloud_auth',
    'require_owner',
    'require_session',
    'require_cloud',
    'require_loopback',
    'require_https',
    'authority',
    'context',
    'require',
    'auth',
)
STATIC_OK = {
    '/health',
    '/health/model',
    '/dashboard-ui',
    '/iphone/connector-ui.js',
    '/iphone/workflow-budget-ui.js',
    '/capabilities/',
    '/connector-oauth/callback',
    '/iphone',
    '/iphone/',
    '/iphone/manifest.webmanifest',
    '/iphone/sw.js',
    '/iphone/api/access/options',
}


def _functions(lines: list[str]) -> list[tuple[str, int, str]]:
    found = []
    for index, line in enumerate(lines):
        match = re.match(r'^(\s*)(?:async\s+)?def (\w+)\(', line)
        if not match:
            continue
        indent = len(match.group(1))
        body = [line]
        for nxt in lines[index + 1:]:
            if nxt.strip():
                level = len(nxt) - len(nxt.lstrip(' '))
                if level <= indent and re.match(r'\s*(?:async\s+)?(?:def |class |@)', nxt):
                    break
            body.append(nxt)
        found.append((match.group(2), index + 1, '\n'.join(body)))
    return found


def _decorators(path: Path) -> list[tuple[int, str, str]]:
    text = path.read_text(encoding='utf-8', errors='replace')
    prefix = ''
    match = re.search(r"APIRouter\(\s*prefix\s*=\s*['\"]([^'\"]+)['\"]", text)
    if match:
        prefix = match.group(1)
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        deco = re.search(
            r"@(?:app|r|router)\.(get|post|put|patch|delete|websocket)\(\s*['\"]([^'\"]+)",
            line,
        )
        if not deco:
            continue
        raw = deco.group(2)
        full = prefix + raw if raw.startswith('/') else prefix + '/' + raw
        if path.as_posix().endswith('server/connector_knowledge_api.py'):
            full = '/iphone/api/connectors' + raw
        rows.append((number, deco.group(1).upper(), full))
    return rows


def _default_scope(file_text: str, name: str) -> str | None:
    match = re.search(rf"def {name}\([^)]*scope\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]", file_text)
    return match.group(1) if match else None


def derive_route_facts() -> list[dict]:
    facts = []
    for path in sorted(ROOT.rglob('*.py')):
        if any(part in path.parts for part in ('.git', 'tests', '__pycache__', '.venv')):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        lines = text.splitlines()
        functions = _functions(lines)
        by_name = {name: body for name, _line, body in functions}
        rel = path.relative_to(ROOT).as_posix()
        for deco_line, method, route in _decorators(path):
            fn = next((item for item in functions if item[1] > deco_line), None)
            body = fn[2] if fn else ''
            fname = fn[1] and fn[0] if fn else ''
            evidence = ''
            auth = 'none'
            scope = 'none'
            for name in AUTH_NAMES:
                hit = re.search(rf"(?<![\w]){name}\(", body)
                if not hit:
                    continue
                auth = name
                window = body[hit.start():hit.start() + 240]
                evidence = window.splitlines()[0].strip()[:180]
                literals = re.findall(r"['\"]([a-z0-9_]+:[a-z0-9_]+)['\"]", window)
                scope = literals[0] if literals else (_default_scope(text, name) or 'none')
                helper = by_name.get(name)
                if helper and scope == 'none':
                    nested = re.findall(r"['\"]([a-z0-9_]+:[a-z0-9_]+)['\"]", helper)
                    if nested:
                        scope = nested[0]
                    elif 'current_trusted_request' in helper or 'authorize' in helper:
                        scope = 'trusted-session'
                if name in {'authority', 'context', 'require_cloud', 'require_loopback', 'require_https', 'require_session'} and scope == 'none':
                    scope = {
                        'authority': 'trusted-session',
                        'context': 'trusted-session',
                        'require_session': 'trusted-session',
                        'require_cloud': 'cloud-session',
                        'require_loopback': 'loopback',
                        'require_https': 'transport',
                    }[name]
                break
            blob = body
            if auth in by_name:
                blob += '\n' + by_name[auth]
            if 'emergency_stop' in blob:
                estop = 'checked-in-handler'
            elif '.chat(' in body or 'relay.command' in body:
                estop = 'delegated-to-executor-or-relay'
            else:
                estop = 'not-in-handler'
            if 'require_fresh' in blob or 'reauth' in blob:
                approval = 'fresh-reauth'
            elif 'approval' in blob:
                approval = 'mentions-approval'
            else:
                approval = 'none-visible'
            if any(token in body for token in ('Cookie', 'pa_device', 'pa_token')):
                binding = 'device-cookie'
            elif 'Authorization' in body or 'authorization' in body or auth in {'cloud_auth', 'auth_device'}:
                binding = 'bearer'
            elif auth in {'authority', 'context', 'require', 'require_owner', 'require_session', 'authenticate'}:
                binding = 'trusted-session-or-device'
            elif auth == 'require_loopback':
                binding = 'loopback'
            elif auth == 'require_cloud':
                binding = 'owner-or-cloud-session'
            else:
                binding = 'none'
            writes = sorted(set(re.findall(r"\.([a-z_]*?(?:audit|revoke|create|delete|save|write|append|approve|reject|set_emergency_stop)[a-z_]*)\(", blob)))
            if 'pairing.consume' in body:
                auth = 'pairing-code'
                scope = 'enrollment'
                evidence = 'pairing.consume(body.token, body.code)'
                binding = 'one-time-pairing-code'
            if (method, route) in LEGACY and rel == 'server/iphone_pwa.py':
                status = 'legacy-opt-in'
            elif auth != 'none':
                status = 'canonical'
            elif route in STATIC_OK or route.endswith('.js'):
                status = 'surface-specific-ok'
            elif method == 'GET':
                status = 'unproven'
            else:
                status = 'gap'
            facts.append({
                'file': rel,
                'line': deco_line,
                'method': method,
                'path': route,
                'handler': fname,
                'status': status,
                'auth': auth,
                'scope': scope,
                'authority': rel,
                'session_binding': binding,
                'estop': estop,
                'approval': approval,
                'durable_writes': writes,
                'evidence': evidence,
            })
    return facts
