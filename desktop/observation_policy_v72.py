from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

from browser.observation import find_target, safe_browser_evidence, target_for_coordinates


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


class ObservationSafetyError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        self.code = str(code)
        super().__init__(message or self.code)


def _evidence_meta(record: dict, key: str, default=None):
    if key in record: return record.get(key)
    return (record.get('sensitivity') or {}).get(key, default)


def build_observation_record(*, binding, transaction_id: str, application: dict, screen: dict, browser: dict | None, reason: str, initiator: str) -> dict:
    now = float(screen.get('captured_at') or time.time())
    expires_at = float(screen.get('expires_at') or now)
    browser_safe = safe_browser_evidence(browser) if browser else {}
    app = dict(application or {})
    evidence_meta = {
        'redaction_count': int(screen.get('redaction_count') or 0),
        'sensitive_region_count': int(browser_safe.get('sensitive_region_count') or 0),
        'evidence_id': str(screen.get('evidence_id') or screen.get('observation_id') or ''),
        'sanitized_checksum': str(screen.get('sanitized_checksum') or ''),
        'redaction_status': str(screen.get('redaction_status') or ''),
        'redaction_method': str(screen.get('redaction_method') or ''),
        'coordinate_space_version': int(screen.get('coordinate_space_version') or 0),
        'capture_source': str(screen.get('capture_source') or '')[:80],
        'visual_evidence_unavailable': bool(screen.get('visual_evidence_unavailable')),
        'retention_expires_at': float(screen.get('retention_expires_at') or expires_at),
    }
    record = {
        'observation_id': str(screen.get('observation_id') or ''),
        'owner_id': binding.owner_id,
        'device_id': binding.device_id,
        'session_id': binding.session_id,
        'security_epoch': int(binding.security_epoch),
        'transaction_id': str(transaction_id or ''),
        'application_identity': str(app.get('identity_digest') or ''),
        'application_name': str(app.get('application') or '')[:260],
        'process_identity': canonical_digest({'pid': app.get('process_id'), 'start': app.get('process_start_token'), 'exe': app.get('executable')}) if app.get('available') else '',
        'window_identity': str(app.get('window_id') or ''),
        'window_title_digest': str(app.get('window_title_sha256') or ''),
        'browser_context_identity': str(browser_safe.get('browser_context_id') or ''),
        'browser_tab_identity': str(browser_safe.get('tab_id') or ''),
        'browser_origin': str(browser_safe.get('origin') or ''),
        'normalized_url': str(browser_safe.get('normalized_url') or ''),
        'captured_at': now,
        'expires_at': expires_at,
        'screenshot_evidence_ref': str(screen.get('screenshot_evidence_ref') or ''),
        'screen_fingerprint': str(screen.get('screen_fingerprint') or screen.get('screenshot_sha256') or ''),
        **evidence_meta,
        'sanitized_dom_digest': str(browser_safe.get('dom_sha256') or ''),
        'accessibility_tree_digest': str(browser_safe.get('accessibility_sha256') or ''),
        'actionable_element_digest': str(browser_safe.get('actionable_digest') or ''),
        'frame_origins_digest': str(browser_safe.get('frame_origins_digest') or ''),
        'active_target_id': str(browser_safe.get('active_target_id') or ''),
        'sensitivity': evidence_meta,
        'capture_reason': str(reason or '')[:120],
        'capture_initiator': str(initiator or '')[:120],
    }
    required = ('observation_id','owner_id','device_id','session_id','transaction_id','screenshot_evidence_ref','screen_fingerprint','evidence_id','sanitized_checksum','redaction_status','redaction_method','coordinate_space_version')
    if any(record.get(key) in (None, '') for key in required): raise ObservationSafetyError('verification_failed', 'observation record is incomplete')
    if not app.get('available'): raise ObservationSafetyError('application_unavailable', 'foreground application identity is unavailable')
    if not record['application_identity'] or not record['window_identity'] or not record['process_identity']: raise ObservationSafetyError('identity_unavailable', 'foreground application/process/window identity is incomplete')
    if record['redaction_status'] not in {'sanitized','full_frame_redacted'}: raise ObservationSafetyError('verification_failed', 'unknown evidence redaction state')
    record['observation_digest'] = canonical_digest(record)
    return record


def observation_context(record: dict) -> dict:
    out = {key: record.get(key) for key in ('application_identity','process_identity','window_identity','browser_context_identity','browser_tab_identity','browser_origin','normalized_url','sanitized_dom_digest','accessibility_tree_digest','actionable_element_digest','frame_origins_digest')}
    out['redaction_status'] = _evidence_meta(record, 'redaction_status', '')
    out['coordinate_space_version'] = int(_evidence_meta(record, 'coordinate_space_version', 0) or 0)
    return out


def _safe_evidence_path(data_root: Path, ref: str) -> Path:
    root = Path(data_root).resolve(); candidate = (root / str(ref or '')).resolve(strict=True)
    if root != candidate and root not in candidate.parents: raise ObservationSafetyError('verification_failed', 'evidence reference escapes the data root')
    if candidate.is_symlink() or not candidate.is_file(): raise ObservationSafetyError('verification_failed', 'evidence reference is not a regular file')
    return candidate


def screen_region_digest(data_root: Path, evidence_ref: str, x: int, y: int, *, radius: int = 28) -> str:
    from PIL import Image
    path = _safe_evidence_path(data_root, evidence_ref)
    with Image.open(path) as image:
        left=max(0,int(x)-radius); top=max(0,int(y)-radius); right=min(image.width,int(x)+radius+1); bottom=min(image.height,int(y)+radius+1)
        if right<=left or bottom<=top: raise ObservationSafetyError('target_changed', 'target coordinate is outside screenshot bounds')
        crop=image.crop((left,top,right,bottom)).convert('RGB'); payload=crop.tobytes()+f'{crop.size[0]}x{crop.size[1]}'.encode('ascii')
    return hashlib.sha256(payload).hexdigest()


def bind_step_target(step: dict, *, browser_snapshot: dict | None, observation: dict, data_root: Path) -> dict:
    kind=str(step.get('kind') or ''); params=dict(step.get('params') or {}); browser_snapshot=browser_snapshot or {}
    if kind in {'click','move'}:
        if 'x' not in params or 'y' not in params: raise ObservationSafetyError('identity_unavailable', f'{kind} requires explicit target coordinates')
        x,y=int(params['x']),int(params['y']); target=target_for_coordinates(browser_snapshot,x,y) if browser_snapshot else None
        if target:
            return {'mode':'browser_element','target_id':target['target_id'],'geometry_digest':target['geometry_digest'],'x':x,'y':y,'origin':observation.get('browser_origin') or '','tab_id':observation.get('browser_tab_identity') or ''}
        if bool(_evidence_meta(observation, 'visual_evidence_unavailable', False)) or _evidence_meta(observation, 'redaction_status', '') != 'sanitized':
            raise ObservationSafetyError('identity_unavailable', 'unavailable visual evidence cannot prove a coordinate target')
        return {'mode':'visual_region','target_id':canonical_digest({'app':observation.get('application_identity'),'window':observation.get('window_identity'),'x':x,'y':y}),'geometry_digest':screen_region_digest(data_root,observation['screenshot_evidence_ref'],x,y),'x':x,'y':y}
    if kind=='type_text':
        target_id=str(browser_snapshot.get('active_target_id') or '') if browser_snapshot else ''; target=find_target(browser_snapshot,target_id) if target_id and browser_snapshot else None
        if not target or not target.get('actionable') or target.get('sensitive'): raise ObservationSafetyError('identity_unavailable', 'typing requires a verified non-sensitive active element')
        return {'mode':'browser_element','target_id':target_id,'geometry_digest':target['geometry_digest'],'origin':observation.get('browser_origin') or '','tab_id':observation.get('browser_tab_identity') or ''}
    if kind=='hotkey': return {'mode':'window','target_id':observation.get('window_identity'),'geometry_digest':observation.get('application_identity')}
    raise ObservationSafetyError('identity_unavailable', 'unsupported target identity mode')


def verify_material_context(*, expected: dict, current: dict, target_binding: dict, current_browser: dict | None, data_root: Path, now: float | None = None):
    now=time.time() if now is None else float(now)
    if now>=float(expected.get('expires_at') or 0): raise ObservationSafetyError('observation_expired', 'the bound observation expired before dispatch')
    for key in ('owner_id','device_id','session_id'):
        if expected.get(key)!=current.get(key): raise ObservationSafetyError('context_changed', f'{key} changed before dispatch')
    if int(expected.get('security_epoch') or 0)!=int(current.get('security_epoch') or 0): raise ObservationSafetyError('context_changed', 'security epoch changed before dispatch')
    if expected.get('application_identity')!=current.get('application_identity') or expected.get('process_identity')!=current.get('process_identity'): raise ObservationSafetyError('context_changed', 'foreground application/process changed before dispatch')
    if expected.get('window_identity')!=current.get('window_identity'): raise ObservationSafetyError('context_changed', 'foreground window changed before dispatch')
    if expected.get('browser_tab_identity') or expected.get('browser_origin'):
        for key,label in (('browser_context_identity','browser session'),('browser_tab_identity','browser tab'),('browser_origin','browser origin'),('normalized_url','browser URL'),('frame_origins_digest','frame origins')):
            if expected.get(key)!=current.get(key): raise ObservationSafetyError('context_changed', f'{label} changed before dispatch')
        if int((current.get('sensitivity') or {}).get('sensitive_region_count') or 0)>int((expected.get('sensitivity') or {}).get('sensitive_region_count') or 0): raise ObservationSafetyError('target_changed', 'a new sensitive field appeared before dispatch')
    mode=target_binding.get('mode')
    if mode=='browser_element':
        target=find_target(current_browser or {},str(target_binding.get('target_id') or ''))
        if not target or not target.get('actionable') or target.get('sensitive'): raise ObservationSafetyError('target_changed', 'the approved actionable target no longer exists')
        if target.get('geometry_digest')!=target_binding.get('geometry_digest'): raise ObservationSafetyError('target_changed', 'the approved target moved or changed geometry')
    elif mode=='visual_region':
        if bool(_evidence_meta(current, 'visual_evidence_unavailable', False)) or _evidence_meta(current, 'redaction_status', '') != 'sanitized': raise ObservationSafetyError('verification_failed', 'current visual evidence cannot verify a coordinate target')
        digest=screen_region_digest(data_root,current['screenshot_evidence_ref'],int(target_binding['x']),int(target_binding['y']))
        if digest!=target_binding.get('geometry_digest'): raise ObservationSafetyError('target_changed', 'the coordinate target region changed before dispatch')
    elif mode=='window':
        if target_binding.get('target_id')!=current.get('window_identity'): raise ObservationSafetyError('target_changed', 'the hotkey target window changed before dispatch')
    else: raise ObservationSafetyError('identity_unavailable', 'the approved target identity is unavailable')
    return True
