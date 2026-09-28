from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping
import uuid


UTC = timezone.utc


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class AdapterCapability:
    adapter_id: str
    modality: str
    state: str
    device_id: str | None = None
    simulation_only: bool = False
    updated_at: str | None = None
    detail: dict[str, Any] | None = None


class ObservationAdapter:
    """Canonical P7 adapter contract. Capability state is reported, never inferred."""

    def __init__(
        self,
        adapter_id: str,
        modality: str,
        *,
        device_id: str | None = None,
        capability_state: str = 'unsupported',
        simulation_only: bool = False,
    ):
        self.adapter_id = str(adapter_id)
        self.modality = str(modality)
        self.device_id = device_id
        self.capability_state = str(capability_state)
        self.simulation_only = bool(simulation_only)

    def register(self, world: "WorldUnderstanding", *, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return world.record_capability(
            self.adapter_id,
            self.modality,
            self.capability_state,
            device_id=self.device_id,
            simulation_only=self.simulation_only,
            detail=detail,
        )

    def ingest(self, world: "WorldUnderstanding", payload: Mapping[str, Any], *, source_event_id: str, **kwargs):
        return world.ingest_from_adapter(self, payload, source_event_id=source_event_id, **kwargs)


class SimulatedObservationAdapter(ObservationAdapter):
    """Deterministic repository-test adapter. Never represents a physical sensor."""

    def __init__(self, adapter_id: str, modality: str, *, device_id: str | None = None):
        super().__init__(
            adapter_id, modality, device_id=device_id, capability_state='simulation_only', simulation_only=True
        )

    def register(self, world: "WorldUnderstanding", *, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return super().register(world, detail={'fixture': True, **dict(detail or {})})

    def ingest(self, world: "WorldUnderstanding", payload: Mapping[str, Any], *, source_event_id: str, **kwargs):
        self.register(world)
        return super().ingest(world, payload, source_event_id=source_event_id, **kwargs)


class WorldUnderstanding:
    """P7 normalized multimodal observation ledger.

    This class owns observation normalization and evidence/context persistence only.
    It never owns action permission, approval, execution, recovery, or memory authority.
    """

    MODALITIES = {'screen', 'camera', 'image', 'document', 'audio', 'location', 'device_sensor', 'wearable'}
    LINEAGE_STAGES = {'raw', 'extracted', 'interpreted', 'derived'}
    CAPABILITY_STATES = {
        'supported', 'available', 'permission_required', 'denied', 'unavailable',
        'offline', 'unsupported', 'simulation_only',
    }
    CLASSIFICATIONS = {'public', 'normal', 'internal', 'sensitive', 'secret'}
    RETENTION_POLICIES = {'ephemeral', 'standard', 'long', 'owner_hold'}
    PUBLIC_CONTEXT_CLASSIFICATIONS = {'public', 'normal', 'internal'}
    SCHEMA_VERSION = 2

    MAX_PAYLOAD_BYTES = 64 * 1024
    MAX_STRING_CHARS = 8192
    MAX_COLLECTION_ITEMS = 128
    MAX_METADATA_KEYS = 64
    MAX_DEPTH = 8
    MAX_FUTURE_SKEW_SECONDS = 300

    FORBIDDEN_KEYS = {
        'password', 'passwd', 'passphrase', 'secret', 'client_secret', 'api_key', 'apikey',
        'token', 'access_token', 'refresh_token', 'authorization', 'cookie', 'set_cookie',
        'credential', 'credentials', 'private_key', 'bearer_token', 'session_token',
    }
    REFERENCE_KEYS = {'path', 'file', 'file_path', 'local_path', 'url', 'uri', 'content_url', 'content_uri'}
    SAFE_REFERENCE_SCHEMES = ('blob:', 'object:', 'attachment:', 'observation:')

    FRESHNESS_TTLS = {
        'screen': 120,
        'camera': 300,
        'image': 300,
        'document': None,
        'audio': 300,
        'location': 120,
        'device_sensor': 300,
        'wearable': 300,
    }
    RETENTION_TTLS = {
        'ephemeral': 24 * 60 * 60,
        'standard': 30 * 24 * 60 * 60,
        'long': 365 * 24 * 60 * 60,
        'owner_hold': None,
    }
    CLASSIFICATION_RANK = {'public': 0, 'normal': 1, 'internal': 1, 'sensitive': 2, 'secret': 3}

    def __init__(
        self,
        *,
        gate,
        events=None,
        path: Path | None = None,
        device_registry=None,
        audit=None,
        clock=None,
    ):
        self.gate = gate
        self.events = events
        self.device_registry = device_registry
        self.audit = audit
        self.path = Path(path) if path is not None else None
        self._clock = clock or _utc_now
        self._lock = RLock()
        self._memory_rows: dict[str, dict[str, Any]] = {} if path is None else None
        self._memory_capabilities: dict[str, dict[str, Any]] = {} if path is None else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _now(self) -> datetime:
        value = self._clock()
        if isinstance(value, str):
            return self._parse_datetime(value, field='clock', permit_future=True)
        if not isinstance(value, datetime):
            raise TypeError('clock must return datetime or ISO timestamp')
        if value.tzinfo is None:
            raise ValueError('clock must be timezone-aware')
        return value.astimezone(UTC)

    def _con(self):
        if self.path is None:
            raise RuntimeError('database is not configured')
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA secure_delete=ON')
        return con

    def _init_db(self):
        with self._con() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute(
                '''CREATE TABLE IF NOT EXISTS observations(
                    id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    document TEXT NOT NULL
                )'''
            )
            columns = {row['name'] for row in con.execute('PRAGMA table_info(observations)')}
            additions = {
                'source_event_id': 'TEXT',
                'modality': 'TEXT',
                'source': 'TEXT',
                'source_adapter': 'TEXT',
                'device_id': 'TEXT',
                'received_at': 'TEXT',
                'processed_at': 'TEXT',
                'confidence': 'REAL',
                'privacy_classification': "TEXT NOT NULL DEFAULT 'normal'",
                'payload_classification': "TEXT NOT NULL DEFAULT 'normal'",
                'payload_hash': 'TEXT',
                'provenance_json': "TEXT NOT NULL DEFAULT '{}'",
                'parent_ids_json': "TEXT NOT NULL DEFAULT '[]'",
                'lineage_stage': "TEXT NOT NULL DEFAULT 'raw'",
                'derivation_type': 'TEXT',
                'retention_policy': "TEXT NOT NULL DEFAULT 'standard'",
                'retention_state': "TEXT NOT NULL DEFAULT 'active'",
                'expires_at': 'TEXT',
                'deleted_at': 'TEXT',
                'simulation': 'INTEGER NOT NULL DEFAULT 0',
                'schema_version': f'INTEGER NOT NULL DEFAULT {self.SCHEMA_VERSION}',
                'freshness_ttl_seconds': 'INTEGER',
                'safe_summary': 'TEXT',
                'device_trust_state': "TEXT NOT NULL DEFAULT 'unknown'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    con.execute(f'ALTER TABLE observations ADD COLUMN {name} {definition}')
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS observation_parents(
                    child_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    PRIMARY KEY(child_id,parent_id),
                    FOREIGN KEY(child_id) REFERENCES observations(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_id) REFERENCES observations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS observation_capabilities(
                    adapter_id TEXT PRIMARY KEY,
                    modality TEXT NOT NULL,
                    state TEXT NOT NULL,
                    device_id TEXT,
                    simulation INTEGER NOT NULL DEFAULT 0,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS p7_schema_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_observations_time ON observations(observed_at DESC,id);
                CREATE INDEX IF NOT EXISTS idx_observations_modality_time ON observations(modality,observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_observations_source_time ON observations(source,observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_observations_device_time ON observations(device_id,observed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_observations_retention ON observations(retention_state,expires_at);
                CREATE INDEX IF NOT EXISTS idx_observation_parents_parent ON observation_parents(parent_id,child_id);
                '''
            )
            self._migrate_legacy_rows(con)
            con.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_source_event ON observations(source,source_event_id)'
            )
            con.execute(
                "INSERT INTO p7_schema_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(self.SCHEMA_VERSION),),
            )

    def _migrate_legacy_rows(self, con):
        rows = con.execute(
            'SELECT id,observed_at,document FROM observations WHERE source_event_id IS NULL OR modality IS NULL OR source IS NULL'
        ).fetchall()
        for row in rows:
            try:
                document = json.loads(row['document'] or '{}')
            except Exception:
                document = {}
            modality = str(document.get('modality') or 'document').strip().lower()
            if modality not in self.MODALITIES:
                modality = 'document'
            source = ' '.join(str(document.get('source') or 'legacy').split())[:160] or 'legacy'
            payload = document.get('payload') if isinstance(document.get('payload'), dict) else {}
            try:
                payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            except Exception:
                payload_json = '{}'
            source_event_id = str(document.get('source_event_id') or f"legacy:{row['id']}")[:200]
            confidence = document.get('confidence', 1.0)
            try:
                confidence = float(confidence)
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    confidence = 1.0
            except Exception:
                confidence = 1.0
            stamp = str(document.get('observed_at') or row['observed_at'])
            normalized = {
                'id': row['id'], 'observation_id': row['id'], 'source_event_id': source_event_id,
                'modality': modality, 'payload': payload, 'source': source,
                'source_adapter': str(document.get('source_adapter') or source)[:160],
                'device_id': document.get('device_id'), 'confidence': confidence,
                'observed_at': stamp, 'received_at': stamp, 'processed_at': None,
                'privacy_classification': 'normal', 'payload_classification': 'normal',
                'payload_hash': hashlib.sha256(payload_json.encode('utf-8')).hexdigest(),
                'provenance': {'migrated_legacy': True}, 'parent_observation_ids': [],
                'lineage_stage': 'raw', 'derivation_type': None, 'retention_policy': 'standard',
                'retention_state': 'active', 'expires_at': None, 'deleted_at': None,
                'simulation': False, 'schema_version': self.SCHEMA_VERSION,
                'freshness_ttl_seconds': self.FRESHNESS_TTLS[modality],
                'safe_summary': f'Legacy {modality} observation', 'device_trust_state': 'unknown',
            }
            con.execute(
                '''UPDATE observations SET document=?,source_event_id=?,modality=?,source=?,source_adapter=?,device_id=?,
                   received_at=?,confidence=?,privacy_classification='normal',payload_classification='normal',payload_hash=?,
                   provenance_json=?,parent_ids_json='[]',lineage_stage='raw',retention_policy='standard',retention_state='active',
                   simulation=0,schema_version=?,freshness_ttl_seconds=?,safe_summary=?,device_trust_state='unknown'
                   WHERE id=?''',
                (
                    json.dumps(normalized, sort_keys=True, default=str), source_event_id, modality, source,
                    normalized['source_adapter'], normalized['device_id'], stamp, confidence, normalized['payload_hash'],
                    json.dumps(normalized['provenance'], sort_keys=True), self.SCHEMA_VERSION,
                    normalized['freshness_ttl_seconds'], normalized['safe_summary'], row['id'],
                ),
            )

    @staticmethod
    def _clean_label(value: Any, field: str, max_length: int) -> str:
        text = ' '.join(str(value or '').split())
        if not text:
            raise ValueError(f'{field} is required')
        if len(text) > max_length:
            raise ValueError(f'{field} is too long')
        return text

    def _parse_datetime(self, value: str | datetime, *, field: str, permit_future: bool = False) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value or '').strip()
            if not text:
                raise ValueError(f'{field} is required')
            if text.endswith('Z'):
                text = text[:-1] + '+00:00'
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError as exc:
                raise ValueError(f'invalid {field}') from exc
        if parsed.tzinfo is None:
            raise ValueError(f'{field} must include timezone')
        parsed = parsed.astimezone(UTC)
        if not permit_future:
            now = self._now()
            if parsed > now + timedelta(seconds=self.MAX_FUTURE_SKEW_SECONDS):
                raise ValueError(f'{field} is too far in the future')
        return parsed

    @classmethod
    def _forbidden_key(cls, key: Any) -> bool:
        normalized = str(key).strip().lower().replace('-', '_').replace(' ', '_')
        return (
            normalized in cls.FORBIDDEN_KEYS
            or normalized.endswith('_password')
            or normalized.endswith('_secret')
            or normalized.endswith('_token')
            or normalized.endswith('_credential')
            or normalized.endswith('_credentials')
        )

    @classmethod
    def _unsafe_reference(cls, key: Any, value: Any) -> bool:
        normalized = str(key).strip().lower().replace('-', '_').replace(' ', '_')
        if normalized not in cls.REFERENCE_KEYS or not isinstance(value, str):
            return False
        text = value.strip()
        lowered = text.lower()
        if lowered.startswith(('http://', 'https://', 'file://', 'ftp://')):
            return True
        if text.startswith(('/', '\\')) or '..' in Path(text).parts:
            return True
        if ':' in text and not lowered.startswith(cls.SAFE_REFERENCE_SCHEMES):
            prefix = text.split(':', 1)[0]
            if len(prefix) <= 12:
                return True
        return False

    def _validate_json_value(self, value: Any, *, depth: int = 0, counter: list[int] | None = None, key: str | None = None):
        if depth > self.MAX_DEPTH:
            raise ValueError('payload nesting exceeds limit')
        if counter is None:
            counter = [0]
        if isinstance(value, Mapping):
            if len(value) > self.MAX_METADATA_KEYS:
                raise ValueError('payload object has too many keys')
            output = {}
            for raw_key, child in value.items():
                name = str(raw_key)
                if len(name) > 128:
                    raise ValueError('payload key is too long')
                if self._forbidden_key(name):
                    raise ValueError('secret-bearing payload field is prohibited')
                if self._unsafe_reference(name, child):
                    raise ValueError('unsafe content reference is prohibited')
                counter[0] += 1
                if counter[0] > 1024:
                    raise ValueError('payload contains too many values')
                output[name] = self._validate_json_value(child, depth=depth + 1, counter=counter, key=name)
            return output
        if isinstance(value, (list, tuple)):
            if len(value) > self.MAX_COLLECTION_ITEMS:
                raise ValueError('payload collection is too large')
            return [self._validate_json_value(child, depth=depth + 1, counter=counter, key=key) for child in value]
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError('payload numeric value must be finite')
            return value
        if isinstance(value, str):
            if len(value) > self.MAX_STRING_CHARS:
                raise ValueError('payload string is too large')
            if '\x00' in value:
                raise ValueError('payload string contains NUL')
            return value
        raise ValueError('payload contains unsupported value type')

    def _validate_payload(self, modality: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        if not isinstance(payload, Mapping):
            raise ValueError('payload must be an object')
        clean = self._validate_json_value(payload)
        if modality == 'location':
            lat = clean.get('latitude', clean.get('lat'))
            lon = clean.get('longitude', clean.get('lon', clean.get('lng')))
            if lat is None or lon is None:
                raise ValueError('location requires latitude and longitude')
            if isinstance(lat, bool) or isinstance(lon, bool):
                raise ValueError('location coordinates must be numeric')
            try:
                lat_value, lon_value = float(lat), float(lon)
            except (TypeError, ValueError) as exc:
                raise ValueError('location coordinates must be numeric') from exc
            if not math.isfinite(lat_value) or not math.isfinite(lon_value):
                raise ValueError('location coordinates must be finite')
            if not -90 <= lat_value <= 90 or not -180 <= lon_value <= 180:
                raise ValueError('location coordinates out of range')
        if modality in {'device_sensor', 'wearable'} and 'value' in clean:
            sensor_type = str(clean.get('sensor_type') or clean.get('type') or '').strip()
            unit = str(clean.get('unit') or '').strip()
            if not sensor_type or len(sensor_type) > 80:
                raise ValueError('sensor_type is required for sensor values')
            if not unit or len(unit) > 40:
                raise ValueError('unit is required for sensor values')
            value = clean['value']
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError('sensor value must be finite numeric data')
        try:
            encoded = json.dumps(clean, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            encoded_bytes = encoded.encode('utf-8')
        except (UnicodeError, ValueError) as exc:
            raise ValueError('payload contains invalid text or numeric data') from exc
        if len(encoded_bytes) > self.MAX_PAYLOAD_BYTES:
            raise ValueError('payload exceeds maximum size')
        return clean, hashlib.sha256(encoded_bytes).hexdigest()

    def _validate_classification(self, value: str, field: str) -> str:
        clean = str(value or '').strip().lower()
        if clean not in self.CLASSIFICATIONS:
            raise ValueError(f'unsupported {field}')
        return clean

    def _device_trust(self, device_id: str | None, *, simulation: bool) -> str:
        if simulation:
            return 'simulation'
        if not device_id:
            return 'not_applicable'
        if self.device_registry is None:
            return 'unknown'
        if not self.device_registry.is_active(device_id):
            raise PermissionError('source device is not active/trusted')
        return 'trusted'

    def _retention_expiry(self, policy: str, received_at: datetime) -> str | None:
        ttl = self.RETENTION_TTLS[policy]
        return _iso(received_at + timedelta(seconds=ttl)) if ttl is not None else None

    def _emit(self, action: str, **safe_payload):
        payload = dict(safe_payload)
        if self.events:
            self.events.emit(f'world.{action}', **payload)
        if self.audit:
            try:
                self.audit('world', action, payload)
            except Exception:
                pass

    @staticmethod
    def _rejection_reason(exc: Exception, *, modality: str | None = None) -> str:
        if isinstance(exc, PermissionError):
            return 'permission_or_trust_denied'
        if isinstance(exc, RuntimeError):
            return 'adapter_unavailable'
        text = str(exc).lower()
        if 'secret' in text or 'credential' in text or 'token' in text:
            return 'secret_bearing_payload'
        if 'reference' in text or 'path' in text or 'url' in text:
            return 'unsafe_content_reference'
        if 'timestamp' in text or 'observed_at' in text or 'future' in text:
            return 'invalid_timestamp'
        if 'confidence' in text:
            return 'invalid_confidence'
        if 'location' in text or 'coordinate' in text:
            return 'invalid_location'
        if 'sensor' in text or 'unit' in text:
            return 'invalid_sensor_value'
        if modality in {'device_sensor', 'wearable'} and ('numeric' in text or 'finite' in text or 'value' in text):
            return 'invalid_sensor_value'
        if 'source event identity conflict' in text:
            return 'source_event_conflict'
        return 'invalid_observation_payload'

    def record_capability(
        self,
        adapter_id: str,
        modality: str,
        state: str,
        *,
        device_id: str | None = None,
        simulation_only: bool = False,
        detail: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter_id = self._clean_label(adapter_id, 'adapter_id', 160)
        modality = str(modality or '').strip().lower()
        state = str(state or '').strip().lower()
        if modality not in self.MODALITIES:
            raise ValueError('unsupported modality')
        if state not in self.CAPABILITY_STATES:
            raise ValueError('unsupported capability state')
        if simulation_only and state != 'simulation_only':
            raise ValueError('simulated adapters must report simulation_only')
        if state == 'simulation_only' and not simulation_only:
            raise ValueError('simulation_only state must be marked simulated')
        safe_detail = self._validate_json_value(dict(detail or {}))
        stamp = _iso(self._now())
        item = {
            'adapter_id': adapter_id, 'modality': modality, 'state': state, 'device_id': device_id,
            'simulation_only': bool(simulation_only), 'updated_at': stamp, 'detail': safe_detail,
        }
        if self.path is None:
            with self._lock:
                self._memory_capabilities[adapter_id] = item
        else:
            with self._lock, self._con() as con:
                con.execute(
                    '''INSERT INTO observation_capabilities(adapter_id,modality,state,device_id,simulation,detail_json,updated_at)
                       VALUES(?,?,?,?,?,?,?) ON CONFLICT(adapter_id) DO UPDATE SET modality=excluded.modality,
                       state=excluded.state,device_id=excluded.device_id,simulation=excluded.simulation,
                       detail_json=excluded.detail_json,updated_at=excluded.updated_at''',
                    (adapter_id, modality, state, device_id, int(simulation_only), json.dumps(safe_detail, sort_keys=True), stamp),
                )
        self._emit('capability.checked', adapter_id=adapter_id, modality=modality, state=state, simulation_only=bool(simulation_only))
        return item

    def capability(self, adapter_id: str) -> dict[str, Any] | None:
        if self.path is None:
            item = self._memory_capabilities.get(str(adapter_id))
            return dict(item) if item else None
        with self._con() as con:
            row = con.execute('SELECT * FROM observation_capabilities WHERE adapter_id=?', (str(adapter_id),)).fetchone()
        if not row:
            return None
        item = dict(row)
        item['simulation_only'] = bool(item.pop('simulation'))
        item['detail'] = json.loads(item.pop('detail_json') or '{}')
        return item

    def capabilities(self, *, device_id: str | None = None) -> list[dict[str, Any]]:
        if self.path is None:
            values = list(self._memory_capabilities.values())
            return [dict(item) for item in values if device_id is None or item.get('device_id') == device_id]
        query = 'SELECT * FROM observation_capabilities'
        params: list[Any] = []
        if device_id is not None:
            query += ' WHERE device_id=?'
            params.append(device_id)
        query += ' ORDER BY adapter_id'
        with self._con() as con:
            rows = con.execute(query, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item['simulation_only'] = bool(item.pop('simulation'))
            item['detail'] = json.loads(item.pop('detail_json') or '{}')
            output.append(item)
        return output

    def ingest_from_adapter(self, adapter, payload: Mapping[str, Any], *, source_event_id: str, **kwargs):
        modality = str(getattr(adapter, 'modality', '') or '').strip().lower()
        audit_modality = modality if modality in self.MODALITIES else 'unknown'
        try:
            capability = self.capability(adapter.adapter_id)
            if capability is None:
                raise RuntimeError('adapter capability has not been registered')
            if capability['state'] not in {'available', 'simulation_only'}:
                raise PermissionError(f"adapter capability is {capability['state']}")
            simulation = bool(capability['simulation_only'])
            return self.ingest(
                adapter.modality,
                payload,
                source=f'adapter:{adapter.adapter_id}',
                source_adapter=adapter.adapter_id,
                device_id=getattr(adapter, 'device_id', None),
                source_event_id=source_event_id,
                simulation=simulation,
                **kwargs,
            )
        except (RuntimeError, PermissionError, ValueError, TypeError) as exc:
            self._emit(
                'observation.rejected',
                reason=self._rejection_reason(exc, modality=audit_modality),
                modality=audit_modality,
            )
            raise

    def ingest(
        self,
        modality: str,
        payload: Mapping[str, Any],
        *,
        source: str,
        device_id: str | None = None,
        confidence: float = 1.0,
        source_event_id: str | None = None,
        source_adapter: str | None = None,
        observed_at: str | datetime | None = None,
        privacy_classification: str = 'normal',
        payload_classification: str | None = None,
        lineage_stage: str = 'raw',
        parent_observation_ids: list[str] | tuple[str, ...] | None = None,
        derivation_type: str | None = None,
        retention_policy: str = 'standard',
        freshness_ttl_seconds: int | None = None,
        simulation: bool = False,
        safe_summary: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        modality = str(modality or '').strip().lower()
        if modality not in self.MODALITIES:
            self._emit('observation.rejected', reason='unsupported_modality')
            raise ValueError('unsupported modality')
        source = self._clean_label(source, 'source', 160)
        source_adapter = self._clean_label(source_adapter or source, 'source_adapter', 160)
        source_event_id = self._clean_label(source_event_id or f'generated:{uuid.uuid4()}', 'source_event_id', 200)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError('confidence must be numeric') from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('confidence must be finite and between 0 and 1')
        privacy = self._validate_classification(privacy_classification, 'privacy classification')
        payload_class = self._validate_classification(payload_classification or privacy, 'payload classification')
        lineage_stage = str(lineage_stage or '').strip().lower()
        if lineage_stage not in self.LINEAGE_STAGES:
            raise ValueError('unsupported lineage stage')
        parents = tuple(dict.fromkeys(str(item).strip() for item in (parent_observation_ids or ()) if str(item).strip()))
        if len(parents) > 32:
            raise ValueError('too many parent observations')
        if lineage_stage == 'raw' and parents:
            raise ValueError('raw observations cannot claim parent observations')
        if lineage_stage != 'raw' and not parents:
            raise ValueError('derived observations require parent observations')
        if lineage_stage != 'raw' and not str(derivation_type or '').strip():
            raise ValueError('derived observations require derivation_type')
        if derivation_type is not None and len(str(derivation_type)) > 120:
            raise ValueError('derivation_type is too long')
        retention_policy = str(retention_policy or '').strip().lower()
        if retention_policy not in self.RETENTION_POLICIES:
            raise ValueError('unsupported retention policy')
        clean_payload, payload_hash = self._validate_payload(modality, payload)
        clean_provenance = self._validate_json_value(dict(provenance or {}))
        received_dt = self._now()
        observed_dt = self._parse_datetime(observed_at, field='observed_at') if observed_at is not None else received_dt
        ttl = self.FRESHNESS_TTLS[modality] if freshness_ttl_seconds is None else int(freshness_ttl_seconds)
        if ttl is not None and not 0 <= ttl <= 365 * 24 * 60 * 60:
            raise ValueError('freshness_ttl_seconds out of range')
        trust = self._device_trust(device_id, simulation=bool(simulation))
        if safe_summary is None:
            safe_summary = f'{modality} observation from {source}'
        safe_summary = ' '.join(str(safe_summary).split())
        if len(safe_summary) > 512:
            raise ValueError('safe_summary is too long')
        if privacy in {'sensitive', 'secret'}:
            safe_summary = f'{privacy} {modality} observation'
        parent_rows = []
        for parent_id in parents:
            parent = self._get_unfiltered(parent_id)
            if not parent or parent.get('deleted_at') or parent.get('retention_state') != 'active':
                raise ValueError('parent observation is missing or inactive')
            parent_rows.append(parent)
        if parent_rows:
            required_rank = max(self.CLASSIFICATION_RANK.get(row['privacy_classification'], 3) for row in parent_rows)
            if self.CLASSIFICATION_RANK[privacy] < required_rank:
                raise ValueError('derived observation cannot downgrade parent privacy classification')
        observation_id = str(uuid.uuid4())
        expires_at = self._retention_expiry(retention_policy, received_dt)
        item = {
            'id': observation_id,
            'observation_id': observation_id,
            'source_event_id': source_event_id,
            'modality': modality,
            'payload': clean_payload,
            'source': source,
            'source_adapter': source_adapter,
            'device_id': device_id,
            'confidence': confidence,
            'observed_at': _iso(observed_dt),
            'received_at': _iso(received_dt),
            'processed_at': None,
            'privacy_classification': privacy,
            'payload_classification': payload_class,
            'payload_hash': payload_hash,
            'provenance': clean_provenance,
            'parent_observation_ids': list(parents),
            'lineage_stage': lineage_stage,
            'derivation_type': str(derivation_type).strip() if derivation_type else None,
            'retention_policy': retention_policy,
            'retention_state': 'active',
            'expires_at': expires_at,
            'deleted_at': None,
            'simulation': bool(simulation),
            'schema_version': self.SCHEMA_VERSION,
            'freshness_ttl_seconds': ttl,
            'safe_summary': safe_summary,
            'device_trust_state': trust,
        }
        duplicate = self._persist(item)
        duplicate['freshness'] = self.freshness_state(duplicate)
        return duplicate

    def _same_source_event(self, existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        return (
            existing.get('modality') == incoming.get('modality')
            and existing.get('payload_hash') == incoming.get('payload_hash')
            and existing.get('device_id') == incoming.get('device_id')
            and existing.get('lineage_stage') == incoming.get('lineage_stage')
            and list(existing.get('parent_observation_ids') or []) == list(incoming.get('parent_observation_ids') or [])
        )

    def _persist(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.path is None:
            with self._lock:
                for existing in self._memory_rows.values():
                    if existing['source'] == item['source'] and existing['source_event_id'] == item['source_event_id']:
                        if not self._same_source_event(existing, item):
                            raise ValueError('source event identity conflict')
                        return {**existing, 'duplicate': True}
                self._memory_rows[item['id']] = dict(item)
            self._emit('observed', observation_id=item['id'], modality=item['modality'], simulation=item['simulation'], lineage_stage=item['lineage_stage'])
            return {**item, 'duplicate': False}
        document = json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self._lock, self._con() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM observations WHERE source=? AND source_event_id=?', (item['source'], item['source_event_id'])).fetchone()
            if row:
                existing = self._row_item(row)
                if not self._same_source_event(existing, item):
                    raise ValueError('source event identity conflict')
                return {**existing, 'duplicate': True}
            con.execute(
                '''INSERT INTO observations(
                    id,observed_at,document,source_event_id,modality,source,source_adapter,device_id,received_at,processed_at,
                    confidence,privacy_classification,payload_classification,payload_hash,provenance_json,parent_ids_json,
                    lineage_stage,derivation_type,retention_policy,retention_state,expires_at,deleted_at,simulation,
                    schema_version,freshness_ttl_seconds,safe_summary,device_trust_state)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    item['id'], item['observed_at'], document, item['source_event_id'], item['modality'], item['source'],
                    item['source_adapter'], item['device_id'], item['received_at'], item['processed_at'], item['confidence'],
                    item['privacy_classification'], item['payload_classification'], item['payload_hash'],
                    json.dumps(item['provenance'], sort_keys=True), json.dumps(item['parent_observation_ids']), item['lineage_stage'],
                    item['derivation_type'], item['retention_policy'], item['retention_state'], item['expires_at'], item['deleted_at'],
                    int(item['simulation']), item['schema_version'], item['freshness_ttl_seconds'], item['safe_summary'],
                    item['device_trust_state'],
                ),
            )
            for parent_id in item['parent_observation_ids']:
                con.execute('INSERT INTO observation_parents(child_id,parent_id) VALUES(?,?)', (item['id'], parent_id))
        self._emit('observed', observation_id=item['id'], modality=item['modality'], simulation=item['simulation'], lineage_stage=item['lineage_stage'])
        return {**item, 'duplicate': False}

    def _row_item(self, row) -> dict[str, Any]:
        try:
            item = json.loads(row['document'] or '{}')
        except Exception:
            item = {}
        data = dict(row)
        item.update({
            'id': data['id'], 'observation_id': data['id'], 'source_event_id': data.get('source_event_id'),
            'modality': data.get('modality'), 'source': data.get('source'), 'source_adapter': data.get('source_adapter'),
            'device_id': data.get('device_id'), 'confidence': data.get('confidence'), 'observed_at': data.get('observed_at'),
            'received_at': data.get('received_at'), 'processed_at': data.get('processed_at'),
            'privacy_classification': data.get('privacy_classification'), 'payload_classification': data.get('payload_classification'),
            'payload_hash': data.get('payload_hash'), 'lineage_stage': data.get('lineage_stage'),
            'derivation_type': data.get('derivation_type'), 'retention_policy': data.get('retention_policy'),
            'retention_state': data.get('retention_state'), 'expires_at': data.get('expires_at'), 'deleted_at': data.get('deleted_at'),
            'simulation': bool(data.get('simulation')), 'schema_version': data.get('schema_version'),
            'freshness_ttl_seconds': data.get('freshness_ttl_seconds'), 'safe_summary': data.get('safe_summary'),
            'device_trust_state': data.get('device_trust_state'),
        })
        item['provenance'] = json.loads(data.get('provenance_json') or '{}')
        item['parent_observation_ids'] = json.loads(data.get('parent_ids_json') or '[]')
        if data.get('retention_state') != 'active' or data.get('deleted_at'):
            item['payload'] = {}
        return item

    def _get_unfiltered(self, observation_id: str) -> dict[str, Any] | None:
        if self.path is None:
            item = self._memory_rows.get(str(observation_id))
            return dict(item) if item else None
        with self._con() as con:
            row = con.execute('SELECT * FROM observations WHERE id=?', (str(observation_id),)).fetchone()
        return self._row_item(row) if row else None

    def get(self, observation_id: str, *, allowed_classifications=None, include_deleted: bool = False) -> dict[str, Any] | None:
        allowed = set(allowed_classifications or self.PUBLIC_CONTEXT_CLASSIFICATIONS)
        if not allowed.issubset(self.CLASSIFICATIONS):
            raise ValueError('unsupported classification filter')
        item = self._get_unfiltered(observation_id)
        if not item or item.get('privacy_classification') not in allowed:
            return None
        if not include_deleted and (item.get('deleted_at') or item.get('retention_state') != 'active'):
            return None
        item['freshness'] = self.freshness_state(item)
        return item

    def recent(
        self,
        limit: int = 50,
        *,
        allowed_classifications=None,
        modality: str | None = None,
        source: str | None = None,
        device_id: str | None = None,
        freshness: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        allowed = set(allowed_classifications or self.PUBLIC_CONTEXT_CLASSIFICATIONS)
        if not allowed or not allowed.issubset(self.CLASSIFICATIONS):
            raise ValueError('unsupported classification filter')
        if modality is not None and modality not in self.MODALITIES:
            raise ValueError('unsupported modality')
        if self.path is None:
            rows = list(self._memory_rows.values())
            rows.sort(key=lambda item: (item['observed_at'], item['id']), reverse=True)
            output = []
            for raw in rows:
                if raw['privacy_classification'] not in allowed:
                    continue
                if not include_deleted and (raw.get('deleted_at') or raw.get('retention_state') != 'active'):
                    continue
                if modality and raw['modality'] != modality:
                    continue
                if source and raw['source'] != source:
                    continue
                if device_id and raw.get('device_id') != device_id:
                    continue
                item = dict(raw)
                item['freshness'] = self.freshness_state(item)
                if freshness and item['freshness'] != freshness:
                    continue
                output.append(item)
                if len(output) >= limit:
                    break
            return output
        placeholders = ','.join('?' for _ in allowed)
        clauses = [f'privacy_classification IN ({placeholders})']
        params: list[Any] = sorted(allowed)
        if not include_deleted:
            clauses.extend(["retention_state='active'", 'deleted_at IS NULL'])
        if modality:
            clauses.append('modality=?'); params.append(modality)
        if source:
            clauses.append('source=?'); params.append(source)
        if device_id:
            clauses.append('device_id=?'); params.append(device_id)
        sql_limit = min(2000, max(limit * 8, limit)) if freshness else limit
        params.append(sql_limit)
        with self._con() as con:
            rows = con.execute(
                f"SELECT * FROM observations WHERE {' AND '.join(clauses)} ORDER BY observed_at DESC,id DESC LIMIT ?",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = self._row_item(row)
            item['freshness'] = self.freshness_state(item)
            if freshness and item['freshness'] != freshness:
                continue
            output.append(item)
            if len(output) >= limit:
                break
        return output

    def count(self, *, allowed_classifications=None, include_deleted: bool = False) -> int:
        allowed = set(allowed_classifications or self.PUBLIC_CONTEXT_CLASSIFICATIONS)
        if not allowed or not allowed.issubset(self.CLASSIFICATIONS):
            raise ValueError('unsupported classification filter')
        if self.path is None:
            return sum(
                1 for item in self._memory_rows.values()
                if item['privacy_classification'] in allowed
                and (include_deleted or (not item.get('deleted_at') and item.get('retention_state') == 'active'))
            )
        placeholders = ','.join('?' for _ in allowed)
        clauses = [f'privacy_classification IN ({placeholders})']
        params = sorted(allowed)
        if not include_deleted:
            clauses.extend(["retention_state='active'", 'deleted_at IS NULL'])
        with self._con() as con:
            row = con.execute(f"SELECT COUNT(*) AS n FROM observations WHERE {' AND '.join(clauses)}", params).fetchone()
        return int(row['n'])

    def freshness_state(self, observation: Mapping[str, Any], *, at: datetime | None = None) -> str:
        if observation.get('deleted_at') or observation.get('retention_state') == 'deleted':
            return 'expired'
        now = (at or self._now()).astimezone(UTC)
        expires = observation.get('expires_at')
        if expires:
            try:
                if self._parse_datetime(expires, field='expires_at', permit_future=True) <= now:
                    return 'expired'
            except ValueError:
                return 'unknown'
        ttl = observation.get('freshness_ttl_seconds')
        if ttl is None:
            return 'unknown'
        try:
            observed = self._parse_datetime(observation.get('observed_at'), field='observed_at', permit_future=True)
        except ValueError:
            return 'unknown'
        return 'fresh' if (now - observed).total_seconds() <= int(ttl) else 'stale'

    def safe_projection(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        return {
            'observation_id': observation.get('id') or observation.get('observation_id'),
            'source_event_id': observation.get('source_event_id'),
            'modality': observation.get('modality'),
            'source': observation.get('source'),
            'source_adapter': observation.get('source_adapter'),
            'device_id': observation.get('device_id'),
            'device_trust_state': observation.get('device_trust_state'),
            'observed_at': observation.get('observed_at'),
            'received_at': observation.get('received_at'),
            'confidence': observation.get('confidence'),
            'privacy_classification': observation.get('privacy_classification'),
            'lineage_stage': observation.get('lineage_stage'),
            'derivation_type': observation.get('derivation_type'),
            'parent_observation_ids': list(observation.get('parent_observation_ids') or []),
            'freshness': observation.get('freshness') or self.freshness_state(observation),
            'retention_policy': observation.get('retention_policy'),
            'retention_state': observation.get('retention_state'),
            'simulation': bool(observation.get('simulation')),
            'safe_summary': observation.get('safe_summary'),
            'schema_version': observation.get('schema_version'),
        }

    def inspect(self, observation_id: str, *, allowed_classifications=None, include_deleted: bool = False) -> dict[str, Any] | None:
        item = self.get(observation_id, allowed_classifications=allowed_classifications, include_deleted=include_deleted)
        return self.safe_projection(item) if item else None

    def lineage(self, observation_id: str, *, allowed_classifications=None) -> list[dict[str, Any]]:
        allowed = set(allowed_classifications or self.PUBLIC_CONTEXT_CLASSIFICATIONS)
        root = self.get(observation_id, allowed_classifications=allowed)
        if not root:
            return []
        output = []
        seen = set()
        queue = [root]
        while queue and len(output) < 100:
            item = queue.pop(0)
            item_id = item['id']
            if item_id in seen:
                continue
            seen.add(item_id)
            output.append(self.safe_projection(item))
            for parent_id in item.get('parent_observation_ids') or []:
                parent = self.get(parent_id, allowed_classifications=allowed)
                if parent:
                    queue.append(parent)
        return output

    def _descendant_ids(self, observation_id: str) -> list[str]:
        if self.path is None:
            found = {observation_id}
            changed = True
            while changed:
                changed = False
                for item in self._memory_rows.values():
                    if item['id'] not in found and any(parent in found for parent in item.get('parent_observation_ids') or []):
                        found.add(item['id']); changed = True
            return list(found)
        with self._con() as con:
            rows = con.execute(
                '''WITH RECURSIVE descendants(id) AS (
                       SELECT ? UNION SELECT p.child_id FROM observation_parents p JOIN descendants d ON p.parent_id=d.id
                   ) SELECT id FROM descendants''',
                (str(observation_id),),
            ).fetchall()
        return [row['id'] for row in rows]

    def _tombstone(self, item: dict[str, Any], *, state: str, deleted_at: str) -> dict[str, Any]:
        item = dict(item)
        item['payload'] = {}
        item['payload_hash'] = 'deleted'
        item['provenance'] = {}
        item['safe_summary'] = f'{state} observation'
        item['retention_state'] = state
        item['deleted_at'] = deleted_at
        return item

    def delete(self, observation_id: str, *, cascade: bool = True) -> bool:
        existing = self._get_unfiltered(observation_id)
        if not existing:
            return False
        ids = self._descendant_ids(observation_id) if cascade else [str(observation_id)]
        stamp = _iso(self._now())
        if self.path is None:
            with self._lock:
                for item_id in ids:
                    current = self._memory_rows.get(item_id)
                    if current:
                        self._memory_rows[item_id] = self._tombstone(current, state='deleted', deleted_at=stamp)
        else:
            with self._lock, self._con() as con:
                con.execute('BEGIN IMMEDIATE')
                for item_id in ids:
                    row = con.execute('SELECT * FROM observations WHERE id=?', (item_id,)).fetchone()
                    if not row:
                        continue
                    tombstone = self._tombstone(self._row_item(row), state='deleted', deleted_at=stamp)
                    con.execute(
                        '''UPDATE observations SET document=?,payload_hash='deleted',provenance_json='{}',safe_summary=?,
                           retention_state='deleted',deleted_at=? WHERE id=?''',
                        (json.dumps(tombstone, sort_keys=True, default=str), tombstone['safe_summary'], stamp, item_id),
                    )
        self._emit('observation.deleted', observation_id=str(observation_id), cascaded=max(0, len(ids) - 1))
        return True

    def expire_due(self) -> int:
        stamp = _iso(self._now())
        expired_ids: list[str] = []
        if self.path is None:
            with self._lock:
                due_roots = [
                    item['id'] for item in self._memory_rows.values()
                    if item.get('expires_at') and item['expires_at'] <= stamp and item.get('retention_state') == 'active'
                ]
                target_ids: set[str] = set()
                for root_id in due_roots:
                    target_ids.update(self._descendant_ids(root_id))
                for item_id in target_ids:
                    current = self._memory_rows.get(item_id)
                    if not current or current.get('retention_state') != 'active':
                        continue
                    self._memory_rows[item_id] = self._tombstone(current, state='expired', deleted_at=stamp)
                    expired_ids.append(item_id)
        else:
            with self._lock, self._con() as con:
                con.execute('BEGIN IMMEDIATE')
                due_roots = [row['id'] for row in con.execute(
                    "SELECT id FROM observations WHERE retention_state='active' AND deleted_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?",
                    (stamp,),
                ).fetchall()]
                target_ids: set[str] = set()
                for root_id in due_roots:
                    rows = con.execute(
                        '''WITH RECURSIVE descendants(id) AS (
                               SELECT ? UNION SELECT p.child_id FROM observation_parents p JOIN descendants d ON p.parent_id=d.id
                           ) SELECT id FROM descendants''',
                        (root_id,),
                    ).fetchall()
                    target_ids.update(row['id'] for row in rows)
                for item_id in target_ids:
                    row = con.execute(
                        "SELECT * FROM observations WHERE id=? AND retention_state='active' AND deleted_at IS NULL",
                        (item_id,),
                    ).fetchone()
                    if not row:
                        continue
                    tombstone = self._tombstone(self._row_item(row), state='expired', deleted_at=stamp)
                    con.execute(
                        '''UPDATE observations SET document=?,payload_hash='deleted',provenance_json='{}',safe_summary=?,
                           retention_state='expired',deleted_at=? WHERE id=? AND retention_state='active' AND deleted_at IS NULL''',
                        (json.dumps(tombstone, sort_keys=True, default=str), tombstone['safe_summary'], stamp, item_id),
                    )
                    expired_ids.append(item_id)
        for item_id in expired_ids:
            self._emit('observation.expired', observation_id=item_id)
        return len(expired_ids)

    def action_context(
        self,
        *,
        requesting_device_id: str | None = None,
        allowed_classifications=None,
        limit: int = 20,
    ) -> dict[str, Any]:
        decision = self.gate.decision('p7')
        if not decision.allowed:
            return {'allowed_for_governed_action': False, 'reason': decision.reason, 'observations': [], 'source_refs': []}
        if self.device_registry is not None:
            if not requesting_device_id or not self.device_registry.is_active(requesting_device_id):
                return {'allowed_for_governed_action': False, 'reason': 'trusted requesting device required', 'observations': [], 'source_refs': []}
            if hasattr(self.device_registry, 'authorize') and not self.device_registry.authorize(requesting_device_id, 'ai:chat'):
                return {'allowed_for_governed_action': False, 'reason': 'requesting device is not permitted to use AI context', 'observations': [], 'source_refs': []}
        allowed = set(allowed_classifications or self.PUBLIC_CONTEXT_CLASSIFICATIONS)
        observations = self.recent(limit=limit, allowed_classifications=allowed, freshness='fresh')
        projections = [self.safe_projection(item) for item in observations]
        return {
            'allowed_for_governed_action': True,
            'reason': 'P7 context prerequisites satisfied; action authority remains with P6/W7',
            'observations': projections,
            'source_refs': [f"observation:{item['observation_id']}" for item in projections],
            'authorization_granted': False,
        }

    def storage_status(self) -> dict[str, Any]:
        if self.path is None:
            return {'persistent': False, 'loaded_observations_in_memory': len(self._memory_rows), 'schema_version': self.SCHEMA_VERSION}
        with self._con() as con:
            row = con.execute('SELECT COUNT(*) AS n FROM observations').fetchone()
            page_count = int(con.execute('PRAGMA page_count').fetchone()[0])
            page_size = int(con.execute('PRAGMA page_size').fetchone()[0])
        return {
            'persistent': True,
            'observation_count': int(row['n']),
            'loaded_observations_in_memory': 0,
            'database_bytes': page_count * page_size,
            'schema_version': self.SCHEMA_VERSION,
        }
