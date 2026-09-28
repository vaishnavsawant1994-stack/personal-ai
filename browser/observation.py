from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

MAX_VISIBLE_TEXT = 20000
MAX_DOM_CHARS = 30000
MAX_ELEMENTS = 200
_SECRET_WORDS = re.compile(r"password|passwd|secret|token|otp|passcode|pin|cvv|cvc|api[-_ ]?key|private[-_ ]?key|authorization|bearer", re.I)
_SECRET_VALUES = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


def _hash_json(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _redact_text(value: str, limit: int) -> str:
    text = str(value or '')[:max(0, int(limit))]
    for pattern in _SECRET_VALUES:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else '') + '[REDACTED]', text)
    return text


def normalized_url(url: str) -> dict:
    """Return a bounded URL identity without user-info, query or fragment secrets."""
    try:
        parsed = urlsplit(str(url or '')[:8192])
        host = (parsed.hostname or '').casefold().rstrip('.')
        scheme = (parsed.scheme or '').casefold()
        port = parsed.port
        default = (scheme == 'https' and port == 443) or (scheme == 'http' and port == 80)
        netloc = host + (f':{port}' if port and not default else '')
        path = parsed.path[:2048] or '/'
        normalized = urlunsplit((scheme, netloc, path, '', '')) if scheme and netloc else ''
        origin = f'{scheme}://{netloc}' if scheme and netloc else ''
    except Exception:
        host = scheme = normalized = origin = ''
        port = None
        path = ''
    return {'normalized_url': normalized[:4096], 'origin': origin[:1024], 'scheme': scheme, 'domain': host, 'port': port, 'path': path}


def _ensure_page_identity(page) -> tuple[str, str]:
    try:
        tab_id = getattr(page, '_personal_ai_tab_id', '')
        if not tab_id:
            tab_id = f'tab-{uuid.uuid4().hex}'
            setattr(page, '_personal_ai_tab_id', tab_id)
        context = page.context
        context_id = getattr(context, '_personal_ai_context_id', '')
        if not context_id:
            context_id = f'browser-{uuid.uuid4().hex}'
            setattr(context, '_personal_ai_context_id', context_id)
        return context_id, tab_id
    except Exception:
        return '', ''


def _element_identity(item: dict) -> tuple[str, str]:
    semantic = {'tag': str(item.get('tag') or ''), 'role': str(item.get('role') or ''), 'type': str(item.get('type') or ''), 'name': str(item.get('name') or ''), 'label': str(item.get('label') or ''), 'path': str(item.get('path') or '')}
    geometry = item.get('box') if isinstance(item.get('box'), dict) else {}
    return _hash_json(semantic), _hash_json({**semantic, 'box': geometry})


def observe_page(page, *, max_text: int = MAX_VISIBLE_TEXT, max_elements: int = MAX_ELEMENTS) -> dict:
    """Capture one bounded, on-demand, value-redacted browser observation.

    No cookie/storage/header APIs are touched. Input values, hidden fields, script
    content and secret-bearing attributes are excluded before any durable digest
    can be produced.
    """
    now = time.time()
    url_info = normalized_url(getattr(page, 'url', ''))
    browser_context_id, tab_id = _ensure_page_identity(page)
    try:
        title = _redact_text(page.title(), 1000)
    except Exception:
        title = ''
    try:
        visible = _redact_text(page.locator('body').inner_text(timeout=5000), min(int(max_text), MAX_VISIBLE_TEXT))
    except Exception:
        visible = ''

    script = r'''(limit) => {
      const secret = /password|passwd|secret|token|otp|passcode|pin|cvv|cvc|api[-_ ]?key|private[-_ ]?key|authorization|bearer/i;
      const cssPath = (el) => {
        const parts = [];
        let node = el;
        for (let depth = 0; node && node.nodeType === 1 && depth < 7; depth++, node = node.parentElement) {
          let part = node.tagName.toLowerCase();
          const id = node.getAttribute('id') || '';
          if (id && !secret.test(id) && id.length <= 120) { part += '#' + CSS.escape(id); parts.unshift(part); break; }
          const name = node.getAttribute('name') || '';
          if (name && !secret.test(name) && name.length <= 80) part += '[name="' + CSS.escape(name) + '"]';
          let pos = 1, sib = node;
          while ((sib = sib.previousElementSibling)) if (sib.tagName === node.tagName) pos++;
          part += ':nth-of-type(' + pos + ')';
          parts.unshift(part);
        }
        return parts.join('>');
      };
      const nodes = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role],[contenteditable="true"]')).slice(0, limit);
      return nodes.map((el, index) => {
        const rect = el.getBoundingClientRect();
        const type = (el.getAttribute('type') || '').toLowerCase();
        const attrs = [el.getAttribute('name'), el.getAttribute('id'), el.getAttribute('autocomplete'), el.getAttribute('aria-label'), el.getAttribute('placeholder')].filter(Boolean).join(' ');
        const sensitive = type === 'password' || type === 'hidden' || secret.test(attrs);
        const visible = !!(rect.width && rect.height) && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
        const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
        const top = visible ? document.elementFromPoint(cx, cy) : null;
        const topmost = !!top && (top === el || el.contains(top));
        return {
          index,
          tag: el.tagName.toLowerCase(), role: (el.getAttribute('role') || '').slice(0,80), type,
          name: sensitive ? '' : (el.getAttribute('name') || '').slice(0,120),
          label: sensitive ? '[REDACTED]' : (el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0,300),
          text: sensitive ? '[REDACTED]' : (el.innerText || el.textContent || '').trim().slice(0,500),
          placeholder: sensitive ? '[REDACTED]' : (el.getAttribute('placeholder') || '').slice(0,300),
          path: sensitive ? '' : cssPath(el).slice(0,1000),
          sensitive, visible, topmost,
          disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
          box: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)}
        };
      });
    }'''
    try:
        elements = page.evaluate(script, max(1, min(int(max_elements), MAX_ELEMENTS))) or []
    except Exception:
        elements = []

    safe_elements = []
    sensitive_regions = []
    active_target_id = ''
    for item in elements:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if item.get('sensitive') and item.get('visible') and isinstance(item.get('box'), dict):
            sensitive_regions.append(dict(item['box']))
        target_id, geometry_digest = _element_identity(item)
        item['target_id'] = target_id
        item['geometry_digest'] = geometry_digest
        item['actionable'] = bool(item.get('visible') and item.get('topmost') and not item.get('disabled') and not item.get('sensitive'))
        safe_elements.append(item)

    try:
        active_index = page.evaluate(r'''() => {
          const q='a,button,input,textarea,select,[role],[contenteditable="true"]';
          return Array.from(document.querySelectorAll(q)).indexOf(document.activeElement);
        }''')
        if isinstance(active_index, int) and 0 <= active_index < len(safe_elements):
            active_target_id = safe_elements[active_index].get('target_id') or ''
    except Exception:
        pass

    try:
        sanitized_dom = page.evaluate(r'''() => {
          const secret = /password|passwd|secret|token|otp|passcode|pin|cvv|cvc|api[-_ ]?key|private[-_ ]?key|authorization|bearer/i;
          const root = document.documentElement.cloneNode(true);
          root.querySelectorAll('script,style,noscript,template,input[type="hidden"]').forEach(n => n.remove());
          root.querySelectorAll('meta').forEach(n => { if (secret.test((n.getAttribute('name')||'')+' '+(n.getAttribute('http-equiv')||''))) n.remove(); });
          root.querySelectorAll('*').forEach(n => {
            Array.from(n.attributes || []).forEach(a => {
              const k=a.name.toLowerCase();
              if (k === 'value' || k.startsWith('data-') || secret.test(k)) n.removeAttribute(a.name);
              else if (k === 'href' || k === 'src' || k === 'action') {
                try { const u=new URL(a.value, location.href); n.setAttribute(a.name, u.origin + u.pathname); } catch { n.removeAttribute(a.name); }
              }
            });
            if (n.tagName === 'TEXTAREA') n.textContent='';
            if (n.tagName === 'OPTION') n.removeAttribute('value');
            const type=(n.getAttribute('type')||'').toLowerCase();
            const attrs=(n.getAttribute('name')||'')+' '+(n.getAttribute('autocomplete')||'')+' '+(n.getAttribute('aria-label')||'');
            if (type === 'password' || secret.test(attrs)) { n.textContent='[REDACTED]'; n.setAttribute('aria-label','[REDACTED]'); }
          });
          return root.outerHTML;
        }''') or ''
        sanitized_dom = _redact_text(str(sanitized_dom), MAX_DOM_CHARS)
    except Exception:
        sanitized_dom = ''

    try:
        pages = list(page.context.pages)
        tab_index = pages.index(page)
        tab_count = len(pages)
    except Exception:
        tab_index = -1
        tab_count = 0

    try:
        accessibility = _redact_text(page.locator('body').aria_snapshot(timeout=5000), MAX_DOM_CHARS)
        accessibility_available = bool(accessibility)
    except Exception:
        accessibility = ''
        accessibility_available = False

    try:
        frame_origins = sorted({normalized_url(frame.url).get('origin') for frame in page.frames if normalized_url(frame.url).get('origin')})
    except Exception:
        frame_origins = []

    actionable = [{'target_id': e['target_id'], 'geometry_digest': e['geometry_digest'], 'tag': e.get('tag'), 'role': e.get('role')} for e in safe_elements if e.get('actionable')]
    return {
        'captured_at': now,
        'browser': 'chromium',
        'browser_context_id': browser_context_id,
        'tab_id': tab_id,
        'tab_index': tab_index,
        'tab_count': tab_count,
        'title': title,
        **url_info,
        'visible_text': visible,
        'visible_text_sha256': _hash_text(visible),
        'elements': safe_elements,
        'active_target_id': active_target_id,
        'dom': sanitized_dom,
        'dom_sha256': _hash_text(sanitized_dom),
        'accessibility': accessibility,
        'accessibility_sha256': _hash_text(accessibility),
        'accessibility_available': accessibility_available,
        'actionable_digest': _hash_json(actionable),
        'frame_origins_digest': _hash_json(frame_origins),
        'sensitive_regions': sensitive_regions,
        'sensitive_region_count': len(sensitive_regions),
    }


def safe_browser_evidence(snapshot: dict) -> dict:
    """Return durable identifiers and hashes only; never raw DOM/text/values."""
    return {
        'captured_at': snapshot.get('captured_at'),
        'browser': snapshot.get('browser'),
        'browser_context_id': snapshot.get('browser_context_id'),
        'tab_id': snapshot.get('tab_id'),
        'tab_index': snapshot.get('tab_index'),
        'tab_count': snapshot.get('tab_count'),
        'origin': snapshot.get('origin'),
        'normalized_url': snapshot.get('normalized_url'),
        'domain': snapshot.get('domain'),
        'visible_text_sha256': snapshot.get('visible_text_sha256'),
        'dom_sha256': snapshot.get('dom_sha256'),
        'accessibility_sha256': snapshot.get('accessibility_sha256'),
        'accessibility_available': bool(snapshot.get('accessibility_available')),
        'actionable_digest': snapshot.get('actionable_digest'),
        'frame_origins_digest': snapshot.get('frame_origins_digest'),
        'active_target_id': snapshot.get('active_target_id') or '',
        'element_count': len(snapshot.get('elements') or []),
        'sensitive_region_count': len(snapshot.get('sensitive_regions') or []),
    }


def target_for_coordinates(snapshot: dict, x: int, y: int) -> dict | None:
    candidates = []
    for item in snapshot.get('elements') or []:
        box = item.get('box') if isinstance(item, dict) else None
        if not box or not item.get('actionable'):
            continue
        bx, by = float(box.get('x', 0)), float(box.get('y', 0))
        bw, bh = float(box.get('width', 0)), float(box.get('height', 0))
        if bw > 0 and bh > 0 and bx <= x <= bx + bw and by <= y <= by + bh:
            candidates.append((bw * bh, item))
    return dict(min(candidates, key=lambda row: row[0])[1]) if candidates else None


def find_target(snapshot: dict, target_id: str) -> dict | None:
    for item in snapshot.get('elements') or []:
        if isinstance(item, dict) and item.get('target_id') == target_id:
            return dict(item)
    return None
