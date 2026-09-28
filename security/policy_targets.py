from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import mimetypes
import ntpath
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

class TargetValidationError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code

@dataclass(frozen=True)
class NormalizedOrigin:
    scheme: str
    host: str
    port: int
    is_ip_literal: bool
    is_private_network: bool

    @property
    def value(self) -> str:
        default = 443 if self.scheme == 'https' else 80
        suffix = '' if self.port == default else f':{self.port}'
        host = f'[{self.host}]' if ':' in self.host else self.host
        return f'{self.scheme}://{host}{suffix}'

def _idna_host(host: str) -> str:
    value = str(host or '').strip().rstrip('.').lower()
    if not value:
        raise TargetValidationError('domain_not_allowed', 'Destination hostname is missing.')
    try:
        return value.encode('idna').decode('ascii').lower()
    except UnicodeError as exc:
        raise TargetValidationError('domain_not_allowed', 'Destination hostname is not a valid internationalized domain.') from exc

def normalize_origin(url: str, *, allow_ip_literal: bool = False, allow_private_network: bool = False) -> NormalizedOrigin:
    raw = str(url or '').strip()
    try:
        parsed = urlsplit(raw)
    except Exception as exc:
        raise TargetValidationError('domain_not_allowed', 'Destination URL is invalid.') from exc
    if parsed.scheme.lower() not in {'http', 'https'}:
        raise TargetValidationError('domain_not_allowed', 'Only HTTP or HTTPS origins may be authorized.')
    if parsed.username is not None or parsed.password is not None:
        raise TargetValidationError('domain_not_allowed', 'URLs containing embedded credentials are blocked.')
    host = _idna_host(parsed.hostname or '')
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)
    except ValueError as exc:
        raise TargetValidationError('domain_not_allowed', 'Destination port is invalid.') from exc
    ip = None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    private = False
    if ip is not None:
        private = bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast)
        if not allow_ip_literal:
            raise TargetValidationError('destination_not_allowed', 'IP-literal destinations require an explicit owner policy.')
        if private and not allow_private_network:
            raise TargetValidationError('destination_not_allowed', 'Private, localhost, link-local and reserved destinations require an explicit owner policy.')
    return NormalizedOrigin(parsed.scheme.lower(), host, int(port), ip is not None, private)

def normalize_domain_rule(rule: dict) -> dict:
    data = dict(rule or {})
    scheme = str(data.get('scheme') or 'https').lower()
    if scheme not in {'http', 'https'}:
        raise TargetValidationError('domain_not_allowed', 'Domain policy scheme must be HTTP or HTTPS.')
    host = _idna_host(data.get('host') or '')
    if '*' in host:
        raise TargetValidationError('domain_not_allowed', 'Wildcard domain rules are not allowed; use explicit include_subdomains.')
    port = int(data.get('port') or (443 if scheme == 'https' else 80))
    if not (1 <= port <= 65535):
        raise TargetValidationError('domain_not_allowed', 'Domain policy port is invalid.')
    return {'scheme': scheme,'host': host,'port': port,'include_subdomains': bool(data.get('include_subdomains', False)),'allow_ip_literal': bool(data.get('allow_ip_literal', False)),'allow_private_network': bool(data.get('allow_private_network', False))}

def domain_rule_matches(rule: dict, url: str) -> tuple[bool, NormalizedOrigin]:
    policy = normalize_domain_rule(rule)
    origin = normalize_origin(url, allow_ip_literal=policy['allow_ip_literal'], allow_private_network=policy['allow_private_network'])
    host_match = origin.host == policy['host']
    if policy['include_subdomains'] and not host_match:
        host_match = origin.host.endswith('.' + policy['host'])
    return bool(host_match and origin.scheme == policy['scheme'] and origin.port == policy['port']), origin

def redirect_allowed(rule: dict, initial_url: str, final_url: str, *, final_rule: dict | None = None) -> tuple[bool, str]:
    initial_match, initial = domain_rule_matches(rule, initial_url)
    if not initial_match:
        return False, 'redirect_not_allowed'
    try:
        same_rule_match, final = domain_rule_matches(rule, final_url)
    except TargetValidationError:
        same_rule_match = False
        final = None
    if same_rule_match and final is not None and initial.value == final.value:
        return True, 'allow'
    if final_rule is not None:
        try:
            explicit_match, _ = domain_rule_matches(final_rule, final_url)
        except TargetValidationError:
            explicit_match = False
        if explicit_match:
            return True, 'allow_explicit_cross_origin'
    return False, 'redirect_not_allowed'

def file_sha256(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def application_identity(executable: str, *, publisher: str = '', version: str = '') -> dict:
    raw = str(executable or '').strip()
    if not raw:
        raise TargetValidationError('application_not_allowed', 'Application executable identity is unavailable.')
    path = Path(raw).expanduser()
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise TargetValidationError('application_not_allowed', 'Application executable cannot be verified.') from exc
    if not canonical.is_file():
        raise TargetValidationError('application_not_allowed', 'Application executable is not a regular file.')
    return {'canonical_path': str(canonical),'sha256': file_sha256(canonical),'publisher': str(publisher or '').strip(),'version': str(version or '').strip()}

def application_rule_matches(rule: dict, observed: dict) -> tuple[bool, str]:
    policy = dict(rule or {}); actual = dict(observed or {})
    if any(not actual.get(key) for key in ('canonical_path', 'sha256')):
        return False, 'application_not_allowed'
    policy_path = str(policy.get('canonical_path') or ''); actual_path = str(actual.get('canonical_path') or '')
    if os.name == 'nt': policy_path, actual_path = os.path.normcase(policy_path), os.path.normcase(actual_path)
    if policy_path != actual_path: return False, 'application_not_allowed'
    if str(policy.get('sha256') or '').lower() != str(actual.get('sha256') or '').lower(): return False, 'application_changed'
    for field in ('publisher','version'):
        expected = str(policy.get(field) or '').strip()
        if expected and expected != str(actual.get(field) or '').strip(): return False, 'application_changed'
    return True, 'allow'

_WINDOWS_RESERVED = {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
def _looks_windows_path(value: str) -> bool: return bool(re.match(r'^[A-Za-z]:[\\/]', value)) or value.startswith('\\\\')
def _windows_path_checks(raw: str, *, allow_network: bool, path_is_reparse: bool) -> str:
    value = raw.replace('/', '\\')
    if value.startswith('\\\\') and not allow_network: raise TargetValidationError('path_outside_allowed_root', 'UNC/network paths require explicit owner permission.')
    drive, tail = ntpath.splitdrive(value)
    if ':' in tail: raise TargetValidationError('path_outside_allowed_root', 'NTFS alternate data streams are blocked.')
    parts = [part for part in tail.split('\\') if part not in ('', '.')]
    if any(part == '..' for part in parts): raise TargetValidationError('path_outside_allowed_root', 'Path traversal is blocked.')
    for part in parts:
        if part.rstrip(' .').split('.')[0].upper() in _WINDOWS_RESERVED: raise TargetValidationError('path_outside_allowed_root', 'Windows reserved device names are blocked.')
    if path_is_reparse: raise TargetValidationError('path_outside_allowed_root', 'Windows junction/reparse-point targets require explicit qualification.')
    return ntpath.normcase(ntpath.normpath(value))

def canonical_path(path: str, roots: list[str] | tuple[str, ...], *, allow_network: bool = False, path_is_reparse: bool = False, path_is_mounted: bool = False, allow_mounted: bool = False) -> str:
    raw = str(path or '').strip()
    if not raw: raise TargetValidationError('path_outside_allowed_root', 'File path is missing.')
    if path_is_mounted and not allow_mounted: raise TargetValidationError('path_outside_allowed_root', 'Mounted/removable drive access requires an explicit owner policy.')
    if _looks_windows_path(raw) or any(_looks_windows_path(str(root)) for root in roots):
        candidate = _windows_path_checks(raw, allow_network=allow_network, path_is_reparse=path_is_reparse); allowed=[]
        for root in roots:
            normalized = _windows_path_checks(str(root), allow_network=allow_network, path_is_reparse=False)
            try:
                if ntpath.commonpath([candidate, normalized]) == normalized: allowed.append(normalized)
            except ValueError: pass
        if not allowed: raise TargetValidationError('path_outside_allowed_root', 'Path is outside owner-approved roots.')
        return candidate
    candidate = Path(raw).expanduser().resolve(strict=False)
    for parent in [candidate, *candidate.parents]:
        try:
            if parent.exists() and parent.is_symlink(): raise TargetValidationError('path_outside_allowed_root', 'Symlink traversal is blocked.')
        except OSError: raise TargetValidationError('path_outside_allowed_root', 'Path identity cannot be verified.')
    normalized_roots = [Path(root).expanduser().resolve(strict=False) for root in roots]
    if not any(candidate == root or root in candidate.parents for root in normalized_roots): raise TargetValidationError('path_outside_allowed_root', 'Path is outside owner-approved roots.')
    return str(candidate)

_SIGNATURES={'application/pdf':(b'%PDF-',),'image/png':(b'\x89PNG\r\n\x1a\n',),'image/jpeg':(b'\xff\xd8\xff',),'application/zip':(b'PK\x03\x04',b'PK\x05\x06',b'PK\x07\x08')}
def validate_file_metadata(path: str, *, claimed_mime: str = '', max_bytes: int = 50 * 1024 * 1024) -> dict:
    target=Path(path)
    if not target.exists() or not target.is_file(): raise TargetValidationError('path_outside_allowed_root', 'File does not exist or is not a regular file.')
    size=target.stat().st_size
    if size>int(max_bytes): raise TargetValidationError('destination_not_allowed', 'File exceeds the policy size limit.')
    guessed=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'; declared=str(claimed_mime or guessed).lower(); signatures=_SIGNATURES.get(declared)
    if signatures:
        with target.open('rb') as fh: head=fh.read(16)
        if not any(head.startswith(sig) for sig in signatures): raise TargetValidationError('destination_not_allowed', 'File extension/MIME does not match its signature.')
    elif claimed_mime and guessed!='application/octet-stream' and guessed.lower()!=declared: raise TargetValidationError('destination_not_allowed', 'File extension does not match the declared MIME type.')
    return {'size':size,'mime':declared,'extension_mime':guessed}

_SECRET_PATTERNS=(re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),re.compile(r'\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b'),re.compile(r'(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*\S{6,}'))
def classify_clipboard(value: str, *, max_bytes: int = 64 * 1024) -> dict:
    text=str(value or '');raw=text.encode('utf-8')
    if len(raw)>max_bytes: raise TargetValidationError('clipboard_access_blocked', 'Clipboard content exceeds the configured policy limit.')
    secret=any(pattern.search(text) for pattern in _SECRET_PATTERNS);sensitive=secret or bool(re.search(r'(?i)\b(?:ssn|passport|credit card|cvv|one[- ]time code|private key)\b', text));classification='secret' if secret else ('sensitive' if sensitive else 'personal')
    return {'classification':classification,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'secret':secret}
