from __future__ import annotations

import hashlib
import json
import sqlite3
from threading import RLock
from typing import Any, Mapping


class ContinuitySync:
    """P8 sync protocol over the canonical ContinuityService.

    This class owns only cross-device synchronization metadata. Identity, device
    trust, session trust, memory, P7 evidence, P6 operations, approval and action
    authority remain in their existing subsystems.
    """

    MAX_BATCH_EVENTS = 100
    MAX_SERVER_EVENTS = 500
    MAX_PAYLOAD_BYTES = 32 * 1024
    MAX_STRING_CHARS = 8000
    MAX_DEPTH = 6
    ALLOWED_CLIENT_KINDS = {'user_message', 'context_ref'}
    SECRET_KEYS = {
        'password', 'passwd', 'passphrase', 'secret', 'token', 'access_token',
        'refresh_token', 'api_key', 'apikey', 'authorization', 'cookie',
        'credential', 'private_key', 'session_token', 'bearer_token',
    }
    RAW_MULTIMODAL_KEYS = {
        'payload', 'raw_payload', 'raw_content', 'content_bytes', 'image_bytes',
        'audio_bytes', 'document_content', 'location_coordinates',
    }

    def __init__(
        self,
        continuity,
        *,
        gate,
        device_registry,
        security_epoch_provider,
        operations=None,
        world=None,
        events=None,
    ):
        self.continuity = continuity
        self.gate = gate
        self.device_registry = device_registry
        self.security_epoch_provider = security_epoch_provider
        self.operations = operations
        self.world = world
        self.events = events
        self.path = continuity.path
        self._lock = RLock()
        self._init_db()

    def _con(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=30000')
        return con

    def _init_db(self):
        with self._con() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS continuity_sync_state(
                    device_id TEXT PRIMARY KEY,
                    security_epoch INTEGER NOT NULL,
                    last_client_sequence INTEGER NOT NULL DEFAULT 0,
                    last_session_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS continuity_sync_receipts(
                    device_id TEXT NOT NULL,
                    client_event_id TEXT NOT NULL,
                    client_sequence INTEGER NOT NULL,
                    thread_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    server_event_id TEXT NOT NULL,
                    server_sequence INTEGER NOT NULL,
                    security_epoch INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(device_id,client_event_id),
                    UNIQUE(device_id,security_epoch,client_sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_continuity_sync_receipts_thread
                    ON continuity_sync_receipts(thread_id,server_sequence);
                '''
            )

    @staticmethod
    def _normalize_key(value: Any) -> str:
        return str(value).strip().lower().replace('-', '_').replace(' ', '_')

    @classmethod
    def _forbidden_key(cls, key: Any) -> bool:
        name = cls._normalize_key(key)
        return (
            name in cls.SECRET_KEYS
            or name in cls.RAW_MULTIMODAL_KEYS
            or name.endswith('_password')
            or name.endswith('_secret')
            or name.endswith('_token')
            or name.endswith('_credential')
        )

    @classmethod
    def _safe_value(cls, value: Any, *, depth: int = 0):
        if depth > cls.MAX_DEPTH:
            raise ValueError('sync payload nesting exceeds limit')
        if isinstance(value, Mapping):
            if len(value) > 64:
                raise ValueError('sync payload has too many keys')
            result = {}
            for raw_key, child in value.items():
                key = str(raw_key)
                if len(key) > 128:
                    raise ValueError('sync payload key is too long')
                if cls._forbidden_key(key):
                    raise ValueError('secret-bearing or raw multimodal sync field is prohibited')
                result[key] = cls._safe_value(child, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            if len(value) > 128:
                raise ValueError('sync payload collection is too large')
            return [cls._safe_value(item, depth=depth + 1) for item in value]
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if value != value or value in (float('inf'), float('-inf')):
                raise ValueError('sync numeric value must be finite')
            return value
        if isinstance(value, str):
            if len(value) > cls.MAX_STRING_CHARS:
                raise ValueError('sync string is too large')
            if '\x00' in value:
                raise ValueError('sync string contains NUL')
            return value
        raise ValueError('unsupported sync payload type')

    @classmethod
    def _safe_payload(cls, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload or {}, Mapping):
            raise ValueError('sync payload must be an object')
        clean = cls._safe_value(dict(payload or {}))
        encoded = json.dumps(clean, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > cls.MAX_PAYLOAD_BYTES:
            raise ValueError('sync payload exceeds maximum size')
        return clean

    @staticmethod
    def _hash_payload(kind: str, payload: Mapping[str, Any]) -> str:
        raw = json.dumps(
            {'kind': str(kind), 'payload': dict(payload)},
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        ).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def _current_epoch(self) -> int:
        return int(self.security_epoch_provider())

    def _assert_gate(self):
        decision = self.gate.decision('p8')
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _assert_device(self, device_id: str, scope: str = 'ai:chat'):
        self._assert_gate()
        device_id = str(device_id or '').strip()
        if not device_id or not self.device_registry.is_active(device_id):
            raise PermissionError('trusted active device required')
        if hasattr(self.device_registry, 'authorize') and not self.device_registry.authorize(device_id, scope):
            raise PermissionError(f'device is not permitted for {scope}')
        return device_id

    @staticmethod
    def _safe_thread(thread: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if not thread:
            return None
        context = dict(thread.get('context') or {})
        safe_context = {}
        for key in ('surface', 'topic'):
            if key in context and isinstance(context[key], (str, int, float, bool, type(None))):
                safe_context[key] = context[key]
        return {
            'id': thread.get('id'),
            'title': thread.get('title'),
            'context': safe_context,
            'created_at': thread.get('created_at'),
            'updated_at': thread.get('updated_at'),
            'closed_at': thread.get('closed_at'),
        }

    @classmethod
    def _safe_server_event(cls, event: Mapping[str, Any]) -> dict[str, Any]:
        try:
            payload = cls._safe_payload(event.get('payload') or {})
        except ValueError:
            payload = {'redacted': True}
        return {
            'event_id': event.get('event_id'),
            'sequence': event.get('sequence'),
            'thread_id': event.get('thread_id'),
            'device_id': event.get('device_id'),
            'kind': event.get('kind'),
            'payload': payload,
            'created_at': event.get('created_at'),
        }

    def _state(self, device_id: str):
        with self._con() as con:
            return con.execute('SELECT * FROM continuity_sync_state WHERE device_id=?', (device_id,)).fetchone()

    def _prepare_state(self, device_id: str, epoch: int) -> int:
        state = self._state(device_id)
        if state is None or int(state['security_epoch']) != int(epoch):
            return 0
        return int(state['last_client_sequence'])

    def _save_state(self, device_id: str, session_id: str, epoch: int, last_client_sequence: int):
        from devices.continuity import now
        with self._con() as con:
            con.execute(
                '''INSERT INTO continuity_sync_state(
                       device_id,security_epoch,last_client_sequence,last_session_id,updated_at
                   ) VALUES(?,?,?,?,?)
                   ON CONFLICT(device_id) DO UPDATE SET
                       security_epoch=excluded.security_epoch,
                       last_client_sequence=excluded.last_client_sequence,
                       last_session_id=excluded.last_session_id,
                       updated_at=excluded.updated_at''',
                (device_id, int(epoch), int(last_client_sequence), str(session_id), now()),
            )

    def status(self, *, device_id: str, session_id: str) -> dict[str, Any]:
        device_id = self._assert_device(device_id)
        epoch = self._current_epoch()
        thread = self.continuity.active_for_device(
            device_id, authority_guard=lambda: self._assert_device(device_id)
        )
        state = self._state(device_id)
        return {
            'p8_allowed': True,
            'device_id': device_id,
            'session_bound': bool(session_id),
            'security_epoch': epoch,
            'last_client_sequence': int(state['last_client_sequence']) if state is not None and int(state['security_epoch']) == epoch else 0,
            'thread': self._safe_thread(thread),
        }

    def _receipt_by_event(self, device_id: str, event_id: str):
        with self._con() as con:
            return con.execute(
                'SELECT * FROM continuity_sync_receipts WHERE device_id=? AND client_event_id=?',
                (device_id, event_id),
            ).fetchone()

    def _receipt_by_sequence(self, device_id: str, epoch: int, sequence: int):
        with self._con() as con:
            return con.execute(
                'SELECT * FROM continuity_sync_receipts WHERE device_id=? AND security_epoch=? AND client_sequence=?',
                (device_id, int(epoch), int(sequence)),
            ).fetchone()

    def _save_receipt(self, *, device_id: str, event_id: str, client_sequence: int, thread_id: str, payload_hash: str, server_event_id: str, server_sequence: int, epoch: int):
        from devices.continuity import now
        with self._con() as con:
            con.execute(
                '''INSERT INTO continuity_sync_receipts(
                       device_id,client_event_id,client_sequence,thread_id,payload_hash,
                       server_event_id,server_sequence,security_epoch,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)''',
                (device_id, event_id, int(client_sequence), thread_id, payload_hash, server_event_id, int(server_sequence), int(epoch), now()),
            )

    def _append_idempotent(self, thread_id: str, *, device_id: str, kind: str, payload: dict, client_event_id: str):
        from devices.continuity import now
        server_event_id = 'p8:' + hashlib.sha256(f'{device_id}:{client_event_id}'.encode('utf-8')).hexdigest()
        payload_json = json.dumps(payload or {}, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
        stamp = now()
        with self.continuity.lock, self.continuity._con() as con:
            thread = con.execute('SELECT closed_at FROM continuity_threads WHERE id=?', (thread_id,)).fetchone()
            if not thread or thread['closed_at']:
                raise KeyError('active continuity thread not found')
            existing = con.execute('SELECT * FROM continuity_events WHERE event_id=?', (server_event_id,)).fetchone()
            if existing is not None:
                existing_payload = json.dumps(json.loads(existing['payload_json'] or '{}'), sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
                if existing['thread_id'] != thread_id or existing['device_id'] != device_id or existing['kind'] != kind or existing_payload != payload_json:
                    raise ValueError('sync event identity conflict')
                return {'event_id': server_event_id, 'sequence': int(existing['id']), 'thread_id': thread_id, 'duplicate': True}
            cur = con.execute(
                'INSERT INTO continuity_events(event_id,thread_id,device_id,kind,payload_json,created_at) VALUES(?,?,?,?,?,?)',
                (server_event_id, thread_id, device_id, kind, payload_json, stamp),
            )
            sequence = int(cur.lastrowid)
            con.execute('UPDATE continuity_threads SET updated_at=? WHERE id=?', (stamp, thread_id))
        self.continuity.set_active(device_id, thread_id)
        self.continuity._emit('continuity.event', thread_id=thread_id, device_id=device_id, kind=kind, sequence=sequence)
        return {'event_id': server_event_id, 'sequence': sequence, 'thread_id': thread_id, 'duplicate': False}

    def _validate_source_refs(self, payload: Mapping[str, Any], device_id: str):
        refs = payload.get('source_refs')
        if refs is None:
            return
        if not isinstance(refs, list) or len(refs) > 50:
            raise ValueError('source_refs must be a bounded list')
        for ref in refs:
            ref = str(ref)
            if ref.startswith('observation:'):
                if self.world is None:
                    raise ValueError('P7 observation authority unavailable')
                observation_id = ref.split(':', 1)[1]
                allowed = {'public', 'normal', 'internal'}
                if hasattr(self.device_registry, 'authorize') and self.device_registry.authorize(device_id, 'memory:sensitive'):
                    allowed.update({'sensitive', 'secret'})
                item = self.world.inspect(observation_id, allowed_classifications=allowed)
                if not item or item.get('freshness') != 'fresh':
                    raise PermissionError('P7 source reference is unavailable, stale, or restricted')
            elif ref.startswith('operation:'):
                if self.operations is None:
                    raise ValueError('P6 operation authority unavailable')
                if hasattr(self.device_registry, 'authorize') and not self.device_registry.authorize(device_id, 'workflow:read'):
                    raise PermissionError('device cannot read operation status')
                if not self.operations.operation(ref.split(':', 1)[1]):
                    raise KeyError('P6 operation not found')
            elif ref.startswith('memory:'):
                if hasattr(self.device_registry, 'authorize') and not self.device_registry.authorize(device_id, 'memory:read'):
                    raise PermissionError('device cannot read memory references')
            else:
                raise ValueError('unsupported cross-device source reference')

    def _commit_parsed(self, *, device_id: str, session_id: str, current_epoch: int, thread_id: str, parsed):
        """Serialize receipt/state coordination so concurrent delivery stays idempotent.

        Canonical conversation writes still flow through ContinuityService; this lock
        only protects P8's receipt/sequence coordination around those writes.
        """
        with self._lock:
            last_client_sequence = self._prepare_state(device_id, current_epoch)
            accepted = []
            duplicates = []
            for client_sequence, event_id, kind, payload, payload_hash in parsed:
                previous_event = self._receipt_by_event(device_id, event_id)
                if previous_event is not None:
                    if int(previous_event['security_epoch']) != current_epoch or int(previous_event['client_sequence']) != client_sequence or previous_event['thread_id'] != thread_id or previous_event['payload_hash'] != payload_hash:
                        raise ValueError('sync event identity conflict')
                    duplicates.append(event_id)
                    last_client_sequence = max(last_client_sequence, client_sequence)
                    continue
                previous_sequence = self._receipt_by_sequence(device_id, current_epoch, client_sequence)
                if previous_sequence is not None:
                    raise ValueError('sync sequence identity conflict')
                if client_sequence <= last_client_sequence:
                    raise ValueError('out-of-order or replayed sync event')
                server = self._append_idempotent(
                    thread_id, device_id=device_id, kind=kind, payload=payload, client_event_id=event_id,
                )
                self._save_receipt(
                    device_id=device_id, event_id=event_id, client_sequence=client_sequence,
                    thread_id=thread_id, payload_hash=payload_hash, server_event_id=server['event_id'],
                    server_sequence=server['sequence'], epoch=current_epoch,
                )
                last_client_sequence = client_sequence
                accepted.append(event_id)
            self._save_state(device_id, session_id, current_epoch, last_client_sequence)
            return last_client_sequence, accepted, duplicates

    def reconcile(self, *, device_id: str, session_id: str, security_epoch: int, events: list[Mapping[str, Any]] | None = None, thread_id: str | None = None, after_sequence: int = 0, limit: int = 200) -> dict[str, Any]:
        device_id = self._assert_device(device_id)
        current_epoch = self._current_epoch()
        if int(security_epoch) != current_epoch:
            raise PermissionError('stale security epoch')
        if thread_id:
            thread = self.continuity.thread(str(thread_id))
            if not thread or thread.get('closed_at'):
                raise KeyError('active continuity thread not found')
            self.continuity.set_active(device_id, thread['id'])
        else:
            thread = self.continuity.active_for_device(device_id)
            if thread is None:
                created = self.continuity.create_thread('Current context', device_id=device_id)
                thread = self.continuity.thread(created)
        incoming = list(events or [])
        if len(incoming) > self.MAX_BATCH_EVENTS:
            raise ValueError('sync batch is too large')
        parsed = []
        batch_sequences = set()
        batch_event_ids = set()
        for raw in incoming:
            if not isinstance(raw, Mapping):
                raise ValueError('sync event must be an object')
            event_id = str(raw.get('client_event_id') or '').strip()
            if not event_id or len(event_id) > 160:
                raise ValueError('client_event_id is required and bounded')
            try:
                client_sequence = int(raw.get('client_sequence'))
            except (TypeError, ValueError) as exc:
                raise ValueError('client_sequence must be a positive integer') from exc
            if client_sequence <= 0:
                raise ValueError('client_sequence must be a positive integer')
            if event_id in batch_event_ids:
                raise ValueError('duplicate client_event_id inside sync batch')
            if client_sequence in batch_sequences:
                raise ValueError('duplicate client_sequence inside sync batch')
            batch_event_ids.add(event_id)
            batch_sequences.add(client_sequence)
            kind = str(raw.get('kind') or '').strip()
            if kind not in self.ALLOWED_CLIENT_KINDS:
                raise ValueError('unsupported client sync event kind')
            payload = self._safe_payload(raw.get('payload') or {})
            self._validate_source_refs(payload, device_id)
            parsed.append((client_sequence, event_id, kind, payload, self._hash_payload(kind, payload)))
        parsed.sort(key=lambda row: row[0])
        last_client_sequence, accepted, duplicates = self._commit_parsed(
            device_id=device_id,
            session_id=session_id,
            current_epoch=current_epoch,
            thread_id=thread['id'],
            parsed=parsed,
        )
        server_limit = max(1, min(int(limit), self.MAX_SERVER_EVENTS))
        after = max(0, int(after_sequence))
        server_events = [self._safe_server_event(item) for item in self.continuity.events_for_thread(thread['id'], after_sequence=after, limit=server_limit)]
        self._emit('continuity.sync', device_id=device_id, thread_id=thread['id'], accepted=len(accepted), duplicates=len(duplicates), security_epoch=current_epoch)
        return {
            'thread': self._safe_thread(thread), 'security_epoch': current_epoch,
            'last_client_sequence': last_client_sequence,
            'accepted_client_event_ids': accepted, 'duplicate_client_event_ids': duplicates,
            'server_events': server_events, 'after_sequence': after,
        }

    def handoff(self, *, device_id: str, session_id: str, to_device: str, thread_id: str | None = None) -> dict[str, Any]:
        source = self._assert_device(device_id)
        target = self._assert_device(to_device)
        thread = self.continuity.thread(thread_id) if thread_id else self.continuity.active_for_device(
            source, authority_guard=lambda: self._assert_device(source)
        )
        if not thread or thread.get('closed_at'):
            raise KeyError('active continuity thread not found')
        # Connection-time trust is not durable authority. Revalidate both
        # endpoints at the final handoff activation boundary.
        source = self._assert_device(source)
        target = self._assert_device(target)

        def handoff_authority_guard():
            self._assert_device(source)
            self._assert_device(target)

        self.continuity.set_active(target, thread['id'], authority_guard=handoff_authority_guard)
        event = self.continuity.append(thread['id'], device_id=source, kind='handoff', payload={'from_device': source, 'to_device': target})
        self._emit('continuity.handoff', thread_id=thread['id'], from_device=source, to_device=target)
        return {
            'thread': self._safe_thread(thread), 'to_device': target,
            'event': self._safe_server_event({**event, 'device_id': source, 'kind': 'handoff', 'payload': {'from_device': source, 'to_device': target}, 'created_at': None}),
        }

    def operation_status(self, operation_id: str, *, device_id: str, session_id: str) -> dict[str, Any]:
        self._assert_device(device_id, 'workflow:read')
        if self.operations is None:
            raise KeyError('P6 operation authority unavailable')
        operation = self.operations.operation(str(operation_id))
        if not operation:
            raise KeyError('P6 operation not found')
        return {
            'operation_id': operation.get('operation_id'), 'plan_id': operation.get('plan_id'),
            'status': operation.get('status'), 'outcome_state': operation.get('outcome_state'),
            'current_step': operation.get('current_step'), 'risk_summary': operation.get('risk_summary'),
            'source_refs': list(operation.get('source_refs') or []), 'created_at': operation.get('created_at'),
            'updated_at': operation.get('updated_at'), 'completed_at': operation.get('completed_at'),
        }

    def observation_status(self, observation_id: str, *, device_id: str, session_id: str) -> dict[str, Any]:
        device_id = self._assert_device(device_id)
        if self.world is None:
            raise KeyError('P7 observation authority unavailable')
        allowed = {'public', 'normal', 'internal'}
        if hasattr(self.device_registry, 'authorize') and self.device_registry.authorize(device_id, 'memory:sensitive'):
            allowed.update({'sensitive', 'secret'})
        item = self.world.inspect(str(observation_id), allowed_classifications=allowed)
        if not item:
            raise KeyError('P7 observation not found or restricted')
        return item

    def _emit(self, event: str, **payload):
        if self.events:
            self.events.emit(event, **payload)
