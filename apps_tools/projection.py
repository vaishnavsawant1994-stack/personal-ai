from __future__ import annotations

from activities.projection import ActivitiesProjection
from security.projection_redaction import sanitize_sensitive_text


class AppsToolsProjection:
    """Owner-safe read projection over canonical ToolRegistry/integration lifecycle.

    This object is not an execution, registry, connection, or policy authority.
    It exposes only bounded metadata derived from the existing authorities.
    """

    MAX_ITEMS = 200
    MAX_RECENT = 20

    def __init__(self, tool_registry, integrations, audit_store=None):
        self.tools = tool_registry
        self.integrations = integrations
        self.activities = ActivitiesProjection(audit_store) if audit_store is not None else None

    @staticmethod
    def _text(value, limit=500):
        return sanitize_sensitive_text(str(value or ''))[:limit]

    @staticmethod
    def _category(name: str, connector_id: str | None = None) -> str:
        value = f'{connector_id or ""} {name}'.lower()
        if any(x in value for x in ('gmail', 'mail', 'slack', 'message', 'calendar')):
            return 'Communication'
        if any(x in value for x in ('file', 'drive', 'document', 'sheet')):
            return 'Files'
        if any(x in value for x in ('browser', 'web', 'http', 'search')):
            return 'Web'
        if any(x in value for x in ('device', 'desktop', 'computer', 'camera', 'microphone')):
            return 'Devices'
        if any(x in value for x in ('automation', 'workflow')):
            return 'Automation'
        if any(x in value for x in ('knowledge', 'memory')):
            return 'Knowledge'
        if any(x in value for x in ('code', 'github', 'terminal')):
            return 'Development'
        return 'System'

    @staticmethod
    def _approval_summary(tool, registry) -> str:
        if bool(getattr(registry, 'emergency_stop', False)):
            return 'blocked_by_emergency_stop'
        if bool(getattr(tool, 'prohibited', False)):
            return 'blocked_by_policy'
        if bool(getattr(tool, 'requires_reauth', False)):
            return 'reauth_required'
        # Metadata projection must remain pure: ToolRegistry.authorize() may run
        # trusted preparation/destination policy intended only for real execution.
        # Static approval visibility therefore uses the canonical PermissionEngine;
        # dynamic execution policy is re-evaluated by ToolRegistry at execution.
        try:
            decision = registry.permissions.decide(int(tool.risk), confirmed=False)
        except Exception:
            return 'policy_evaluation_required'
        if not decision.allowed and bool(getattr(decision, 'needs_confirmation', False)):
            return 'approval_required'
        if decision.allowed:
            return 'allowed_under_current_policy'
        return 'blocked_by_policy'

    def _connector_map(self):
        if self.integrations is None:
            return {}
        return {str(item.get('id')): item for item in self.integrations.list()[:self.MAX_ITEMS]}

    def _tool(self, tool, connectors):
        connector_id = self._text(getattr(tool, 'connector_id', None), 100) or None
        connector = connectors.get(connector_id) if connector_id else None
        prohibited = bool(getattr(tool, 'prohibited', False))
        if bool(getattr(self.tools, 'emergency_stop', False)):
            availability = 'EMERGENCY_STOP'
        elif prohibited:
            availability = 'PERMISSION_BLOCKED'
        elif connector:
            state = str(connector.get('state') or 'disconnected')
            if state == 'not_configured': availability = 'NOT_CONFIGURED'
            elif state in {'authentication_required', 'authentication_expired', 'disconnected', 'revoked'}: availability = 'CONNECTION_REQUIRED'
            elif state in {'permission_denied', 'insufficient_scope', 'disabled'}: availability = 'PERMISSION_BLOCKED'
            elif state in {'degraded', 'timeout', 'provider_unavailable', 'invalid_response', 'verification_failed', 'rate_limited', 'quota_exceeded'}: availability = 'ERROR'
            elif state == 'healthy': availability = 'AVAILABLE'
            else: availability = 'UNAVAILABLE'
        else:
            availability = 'AVAILABLE'
        return {
            'tool_id': self._text(getattr(tool, 'name', ''), 200),
            'name': self._text(getattr(tool, 'name', ''), 200),
            'description': self._text(getattr(tool, 'description', ''), 1000),
            'category': self._category(getattr(tool, 'name', ''), connector_id),
            'capability': self._text(getattr(tool, 'capability', None), 300) or None,
            'connector_id': connector_id,
            'availability': availability,
            'approval_policy': self._approval_summary(tool, self.tools),
            'requires_reauth': bool(getattr(tool, 'requires_reauth', False)),
            'verification_required': bool(getattr(tool, 'verification_required', False)),
            'risk': getattr(getattr(tool, 'risk', None), 'name', None),
        }

    def tools_list(self):
        connectors = self._connector_map()
        values = [self._tool(tool, connectors) for tool in self.tools.all()[:self.MAX_ITEMS]]
        values.sort(key=lambda item: (item['category'], item['name']))
        return values

    def tool_detail(self, tool_id: str):
        wanted = str(tool_id or '').strip()
        if not wanted or len(wanted) > 200:
            return None
        try:
            tool = self.tools.get(wanted)
        except Exception:
            return None
        projected = self._tool(tool, self._connector_map())
        recent = []
        if self.activities is not None:
            for row in self.activities.list(limit=self.activities.MAX_PAGE, category='tool'):
                details = row.get('details') if isinstance(row.get('details'), dict) else {}
                identity = details.get('tool_id', details.get('tool'))
                if identity is not None and str(identity) == wanted:
                    recent.append(row)
                    if len(recent) >= self.MAX_RECENT:
                        break
        return {**projected, 'recent_activities': recent}

    def apps_list(self):
        if self.integrations is None:
            return []
        out = []
        for item in self.integrations.list()[:self.MAX_ITEMS]:
            state = self._text(item.get('state'), 100) or 'disconnected'
            out.append({
                'app_id': self._text(item.get('id'), 200),
                'name': self._text(item.get('name'), 300),
                'provider': self._text(item.get('provider'), 200),
                'configured': bool(item.get('configured')),
                'connection_status': state,
                'authorization_required': state in {'authentication_required', 'authentication_expired', 'disconnected', 'revoked'},
                'reauth_required': state == 'authentication_expired',
                'capabilities': [self._text(x, 300) for x in list(item.get('capabilities') or [])[:100]],
                'missing_scopes': [self._text(x, 500) for x in list(item.get('missing_scopes') or [])[:100]],
                'last_success_at': item.get('last_success_at'),
                'last_checked_at': item.get('last_checked_at'),
                # Provider errors are not a credential surface. Expose a bounded
                # stable code; do not forward free-form provider text which may
                # echo tokens, URLs, headers, or other secrets.
                'last_error': 'Connector reported an error' if item.get('last_error') else None,
                'last_error_code': self._text(item.get('last_error_code'), 100) or None,
                'revocation_status': self._text(item.get('revocation_status'), 100) or 'none',
                'read_only': bool(item.get('read_only')),
            })
        out.sort(key=lambda item: item['name'])
        return out

    def app_detail(self, app_id: str):
        wanted = str(app_id or '').strip()
        if not wanted or len(wanted) > 200:
            return None
        return next((item for item in self.apps_list() if item['app_id'] == wanted), None)
