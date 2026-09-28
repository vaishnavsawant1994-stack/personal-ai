from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import re
import time
import uuid

from desktop.evidence_geometry import COORDINATE_SPACE_VERSION, CoordinateSpace, GeometryContext, GeometryError, Rect, transform_sensitive_rectangles


class EvidenceGuardError(PermissionError):
    pass


class SanitizedEvidenceGuard:
    """Single screenshot-consumer boundary for OCR/model/vision callers."""
    @staticmethod
    def consume(record: dict, *, owner_id: str = '', device_id: str = '', session_id: str = '', now: float | None = None) -> str:
        now = time.time() if now is None else float(now)
        if record.get('redaction_status') != 'sanitized':
            raise EvidenceGuardError('visual evidence is not marked sanitized')
        if record.get('visual_evidence_unavailable'):
            raise EvidenceGuardError('visual evidence is unavailable')
        if int(record.get('coordinate_space_version') or 0) != COORDINATE_SPACE_VERSION:
            raise EvidenceGuardError('unknown coordinate provenance')
        if now >= float(record.get('expires_at') or 0):
            raise EvidenceGuardError('visual evidence expired')
        for key, expected in (('owner_id', owner_id), ('device_id', device_id), ('session_id', session_id)):
            if expected and str(record.get(key) or '') != str(expected):
                raise EvidenceGuardError(f'visual evidence {key} mismatch')
        raw = bytes(record.get('_sanitized_png') or b'')
        if not raw:
            raise EvidenceGuardError('sanitized visual evidence bytes are unavailable')
        checksum = hashlib.sha256(raw).hexdigest()
        if checksum != str(record.get('sanitized_checksum') or ''):
            raise EvidenceGuardError('visual evidence checksum mismatch')
        return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')


class ScreenUnderstanding:
    def __init__(self, models=None, data_dir: Path | None = None, *, observation_ttl_seconds: int = 120, retention_seconds: int = 86400, max_evidence_files: int = 500):
        self.models = models
        self.data_dir = Path(data_dir or (Path.home() / '.personal_ai'))
        self.observation_ttl_seconds = max(5, min(int(observation_ttl_seconds), 600))
        self.retention_seconds = max(300, int(retention_seconds))
        self.max_evidence_files = max(20, int(max_evidence_files))
        self.guard = SanitizedEvidenceGuard()

    def _evidence_dir(self) -> Path:
        root = self.data_dir
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink():
            raise PermissionError('evidence data root cannot be a symlink')
        directory = root / 'screenshots'
        if directory.exists() and directory.is_symlink():
            raise PermissionError('evidence directory cannot be a symlink')
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.resolve().parent != root.resolve():
            raise PermissionError('evidence directory escapes data root')
        try: os.chmod(directory, 0o700)
        except OSError: pass
        return directory

    @staticmethod
    def _png_bytes(image) -> bytes:
        buf = io.BytesIO(); image.save(buf, format='PNG'); return buf.getvalue()

    def _capture_desktop_image(self, monitor: int):
        import mss
        from PIL import Image
        with mss.mss() as sct:
            index = int(monitor)
            if index < 0 or index >= len(sct.monitors):
                raise ValueError('requested monitor is unavailable')
            mon = dict(sct.monitors[index]); virtual = dict(sct.monitors[0])
            raw = sct.grab(mon)
            image = Image.frombytes('RGB', raw.size, raw.rgb)
        context = GeometryContext(
            monitor_x=float(mon.get('left', 0)), monitor_y=float(mon.get('top', 0)),
            monitor_width=float(mon.get('width', image.width)), monitor_height=float(mon.get('height', image.height)),
            monitor_scale=1.0,
            virtual_origin_x=float(virtual.get('left', 0)), virtual_origin_y=float(virtual.get('top', 0)),
            screenshot_origin_x=float(mon.get('left', 0)), screenshot_origin_y=float(mon.get('top', 0)),
            screenshot_width=float(image.width), screenshot_height=float(image.height), capture_source='desktop_monitor',
        )
        return image, context

    def _sanitize_desktop(self, image, context: GeometryContext, redactions: list[dict] | None, geometry: dict | None):
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        if redactions is None:
            draw.rectangle((0, 0, image.width, image.height), fill=(0, 0, 0))
            return image, 1, 'full_frame_redacted', 'full_frame_fail_safe', True, context
        if not redactions:
            return image, 0, 'sanitized', 'no_sensitive_regions_declared', False, context
        typed = []
        try:
            for raw in redactions[:200]:
                if bool(raw.get('full_screen')):
                    raise GeometryError('full frame requested')
                space = CoordinateSpace(str(raw.get('space') or raw.get('coordinate_space') or ''))
                typed.append(Rect(float(raw['x']), float(raw['y']), float(raw['width']), float(raw['height']), space))
            supplied = GeometryContext(**{k: v for k, v in dict(geometry or {}).items() if k in GeometryContext.__dataclass_fields__})
            supplied = GeometryContext(**{**context.as_dict(), **{k: v for k, v in supplied.as_dict().items() if v not in (None, '')}})
            mapped = transform_sensitive_rectangles(typed, supplied)
            if len(mapped) != len(typed):
                raise GeometryError('one or more sensitive rectangles are outside or invalid')
            for rect in mapped:
                draw.rectangle((int(rect.x), int(rect.y), int(rect.x+rect.width), int(rect.y+rect.height)), fill=(0, 0, 0))
            return image, len(mapped), 'sanitized', 'typed_coordinate_transform', False, supplied
        except Exception:
            draw.rectangle((0, 0, image.width, image.height), fill=(0, 0, 0))
            return image, 1, 'full_frame_redacted', 'full_frame_fail_safe', True, context

    def _secure_write(self, raw: bytes, evidence_id: str) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', str(evidence_id or '')):
            raise ValueError('invalid observation evidence identifier')
        directory = self._evidence_dir(); final_path = directory / f'observation-{evidence_id}.png'
        if final_path.exists() or final_path.is_symlink():
            raise PermissionError('observation evidence destination collision')
        fd = os.open(final_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        except Exception:
            try: final_path.unlink(missing_ok=True)
            except OSError: pass
            raise
        return final_path

    def _prune(self, directory: Path):
        now = time.time()
        files = sorted((p for p in directory.glob('observation-*.png') if p.is_file() and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
        for index, path in enumerate(files):
            try:
                if index >= self.max_evidence_files or now - path.stat().st_mtime > self.retention_seconds:
                    path.unlink(missing_ok=True)
            except OSError: pass

    def observe_record(self, monitor: int = 1, *, redactions: list[dict] | None = None, geometry: dict | None = None, application_context=None, sanitized_source: dict | None = None, evidence_binding: dict | None = None) -> dict:
        from PIL import Image
        binding = dict(evidence_binding or {})
        evidence_id = uuid.uuid4().hex
        captured_at = time.time(); expires_at = captured_at + self.observation_ttl_seconds
        visual_unavailable = False
        if sanitized_source and sanitized_source.get('available') and sanitized_source.get('redaction_status') == 'sanitized':
            source_bytes = bytes(sanitized_source.get('bytes') or b'')
            try:
                image = Image.open(io.BytesIO(source_bytes)).convert('RGB'); image.load()
            except Exception as exc:
                raise EvidenceGuardError('browser-native screenshot is not a valid image') from exc
            raw = self._png_bytes(image)
            redaction_count = int(sanitized_source.get('sensitive_count') or 0)
            redaction_status = 'sanitized'; redaction_method = str(sanitized_source.get('redaction_method') or 'browser_native_element_mask')
            capture_source = str(sanitized_source.get('capture_source') or 'browser_native')
            coordinate_context = dict(sanitized_source.get('geometry') or {})
            coordinate_context.update({'screenshot_width': image.width, 'screenshot_height': image.height, 'capture_source': capture_source})
        else:
            image, desktop_context = self._capture_desktop_image(monitor)
            if sanitized_source and not sanitized_source.get('available'):
                redactions = None
            image, redaction_count, redaction_status, redaction_method, visual_unavailable, applied_context = self._sanitize_desktop(image, desktop_context, redactions, geometry)
            raw = self._png_bytes(image); capture_source = 'desktop_monitor'; coordinate_context = applied_context.as_dict()
        checksum = hashlib.sha256(raw).hexdigest()
        final_path = self._secure_write(raw, evidence_id); self._prune(final_path.parent)
        record = {
            'observation_id': evidence_id,
            'evidence_id': evidence_id,
            'captured_at': captured_at,
            'expires_at': expires_at,
            'retention_expires_at': captured_at + self.retention_seconds,
            'screenshot_evidence_ref': f'screenshots/{final_path.name}',
            'screen_fingerprint': checksum,
            'screenshot_sha256': checksum,
            'sanitized_checksum': checksum,
            'redaction_count': redaction_count,
            'redaction_status': redaction_status,
            'redaction_method': redaction_method,
            'visual_evidence_unavailable': bool(visual_unavailable or redaction_status != 'sanitized'),
            'coordinate_space_version': COORDINATE_SPACE_VERSION,
            'coordinate_provenance': coordinate_context,
            'capture_source': capture_source,
            'monitor': int(monitor),
            'owner_id': str(binding.get('owner_id') or ''), 'device_id': str(binding.get('device_id') or ''), 'session_id': str(binding.get('session_id') or ''),
            'application_context': dict(application_context or {}),
            '_sanitized_png': raw,
        }
        return record

    def capture(self, monitor: int = 1, *, redactions=None, observation_id: str | None = None) -> Path:
        """Compatibility API; never writes an unsanitized intermediate image."""
        record = self.observe_record(monitor, redactions=redactions)
        return self.data_dir / record['screenshot_evidence_ref']

    @staticmethod
    def fingerprint(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def prepare_payload(self, question: str = 'Describe the visible screen.', monitor: int = 1, *, redactions=None, application_context=None, sanitized_source=None, evidence_binding=None):
        record = self.observe_record(monitor, redactions=redactions, application_context=application_context, sanitized_source=sanitized_source, evidence_binding=evidence_binding)
        image_data_url = self.guard.consume(record, owner_id=str((evidence_binding or {}).get('owner_id') or ''), device_id=str((evidence_binding or {}).get('device_id') or ''), session_id=str((evidence_binding or {}).get('session_id') or ''))
        public = {k: v for k, v in record.items() if k != '_sanitized_png'}
        return {**public, 'question': str(question), 'image_data_url': image_data_url}

    def analyze(self, question: str = 'Describe the visible screen and identify actionable UI elements.', monitor: int = 1, *, redactions: list[dict] | None = None, geometry: dict | None = None, application_context=None, sanitized_source=None, evidence_binding=None):
        record = self.observe_record(monitor, redactions=redactions, geometry=geometry, application_context=application_context, sanitized_source=sanitized_source, evidence_binding=evidence_binding)
        if record.get('visual_evidence_unavailable'):
            record.pop('_sanitized_png', None)
            return {**record, 'analysis': 'visual_evidence_unavailable; use sanitized DOM/accessibility evidence only'}
        if self.models is None:
            record.pop('_sanitized_png', None)
            return {**record, 'analysis': 'sanitized screen captured; no vision model configured'}
        image_data = self.guard.consume(record, owner_id=str((evidence_binding or {}).get('owner_id') or ''), device_id=str((evidence_binding or {}).get('device_id') or ''), session_id=str((evidence_binding or {}).get('session_id') or ''))
        prompt = f"{question}\nUse only sanitized visible evidence. If uncertain, say uncertain. Do not infer hidden credentials or secret values."
        response = self.models.vision(prompt, image_data)
        record.pop('_sanitized_png', None)
        return {**record, 'analysis': response}
