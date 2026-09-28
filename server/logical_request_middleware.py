from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from server.logical_request import LogicalTurnBody


_logical_request_id: ContextVar[str | None] = ContextVar('personal_ai_logical_request_id', default=None)
MAX_LOGICAL_TURN_BODY = 16 * 1024


def current_logical_request_id() -> str | None:
    return _logical_request_id.get()


class LogicalRequestMiddleware:
    """Transport V1 request identity; CanonicalTurnRuntime remains replay authority."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self._adapter = Path(__file__).resolve().parent.parent / 'pwa' / 'v1-runtime.js'

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        path = scope.get('path', '')
        method = scope.get('method', '')
        token = None

        if method == 'GET' and path == '/iphone/v1-runtime.js':
            raw = self._adapter.read_bytes()
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/javascript; charset=utf-8'), (b'cache-control', b'no-store'), (b'content-length', str(len(raw)).encode())]})
            await send({'type': 'http.response.body', 'body': raw})
            return

        # Only logical AI-turn endpoints participate. Approval, CRUD, auth and
        # device/control endpoints retain their existing identity semantics.
        if method == 'POST' and path == '/iphone/api/voice/turn':
            body = b''
            more = True
            while more:
                message = await receive()
                if message['type'] != 'http.request':
                    continue
                chunk = message.get('body', b'')
                if len(body) + len(chunk) > MAX_LOGICAL_TURN_BODY:
                    await send({'type': 'http.response.start', 'status': 413, 'headers': [(b'content-type', b'application/json')]})
                    await send({'type': 'http.response.body', 'body': b'{"detail":{"code":"request_too_large","message":"Logical turn request body exceeds the V1 limit."}}'})
                    return
                body += chunk
                more = bool(message.get('more_body', False))
            try:
                payload = json.loads(body or b'{}')
                logical = LogicalTurnBody.model_validate(payload)
            except Exception:
                await send({'type': 'http.response.start', 'status': 422, 'headers': [(b'content-type', b'application/json')]})
                await send({'type': 'http.response.body', 'body': b'{"detail":{"code":"invalid_request_id","message":"A valid client request_id is required."}}'})
                return
            token = _logical_request_id.set(logical.request_id)
            delivered = False

            async def replay_receive() -> Message:
                nonlocal delivered
                if delivered:
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}

            receive = replay_receive

        if method == 'GET' and path in {'/iphone', '/iphone/'}:
            started = None
            chunks: list[bytes] = []

            async def capture(message: Message):
                nonlocal started
                if message['type'] == 'http.response.start':
                    started = message
                    return
                if message['type'] == 'http.response.body':
                    chunks.append(message.get('body', b''))
                    if message.get('more_body'):
                        return
                    raw = b''.join(chunks)
                    if started and int(started.get('status', 0)) == 200 and b'</body>' in raw:
                        raw = raw.replace(b'</body>', b'<script src="/iphone/v1-runtime.js"></script></body>', 1)
                        headers = MutableHeaders(raw=started['headers'])
                        if 'content-length' in headers:
                            headers['content-length'] = str(len(raw))
                    if started:
                        await send(started)
                    await send({'type': 'http.response.body', 'body': raw, 'more_body': False})

            try:
                await self.app(scope, receive, capture)
            finally:
                if token is not None:
                    _logical_request_id.reset(token)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                _logical_request_id.reset(token)
