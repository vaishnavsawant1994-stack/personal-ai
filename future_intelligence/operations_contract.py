from __future__ import annotations

from dataclasses import asdict, dataclass
import uuid
from typing import Any, Iterable

from automation.budget import normalize_policy
from tools.registry import Risk
from future_intelligence.operations_store import _utc_now


@dataclass(frozen=True)
class OperationStep:
    id: str
    kind: str
    instruction: str
    consequential: bool = False
    status: str = 'pending'
    requested_tool: str | None = None
    parameters: dict[str, Any] | None = None
    risk: str = 'READ_ONLY'
    sensitivity: str = 'internal'
    approval_required: bool = False
    requires_reauth: bool = False
    expected_verification: str = 'read_only_observation'
    timeout_seconds: int = 120


class OperationContractMixin:
    @staticmethod
    def _safe_ref_list(values: Iterable[str] | None):
        output = []
        seen = set()
        for value in values or []:
            item = str(value or '').strip()
            if not item or item in seen:
                continue
            output.append(item[:500])
            seen.add(item)
        return output[:100]

    @classmethod
    def _assert_safe_parameters(cls, parameters: dict):
        if not isinstance(parameters, dict):
            raise ValueError('step parameters must be an object')

        def inspect(value, path='parameters'):
            if isinstance(value, dict):
                for key, nested in value.items():
                    low = str(key).strip().lower().replace('-', '_')
                    is_reference = low.endswith(('_ref', '_id')) or low in {'owner_id', 'device_id', 'session_id'}
                    secret_key = low in cls.PRIVATE_PARAMETER_MARKERS or any(
                        low.endswith('_' + marker) for marker in cls.PRIVATE_PARAMETER_MARKERS
                    )
                    if secret_key and not is_reference:
                        raise ValueError(
                            f'raw secret-bearing parameter is forbidden: {path}.{key}; pass an existing reference instead'
                        )
                    inspect(nested, f'{path}.{key}')
            elif isinstance(value, (list, tuple)):
                for index, nested in enumerate(value):
                    inspect(nested, f'{path}[{index}]')

        inspect(parameters)

    def _memory_ids(self, values: Iterable[str] | None, *, allowed_sensitivities=None):
        allowed = {'normal'} if allowed_sensitivities is None else {str(x).strip().lower() for x in allowed_sensitivities}
        output = []
        for memory_id in self._safe_ref_list(values):
            if self.second_brain is None:
                output.append(memory_id)
                continue
            detail = self.second_brain.memory_detail(memory_id)
            if not detail:
                continue
            sensitivity = str(detail.get('sensitivity') or 'normal').strip().lower()
            if sensitivity == 'never_store' or sensitivity not in allowed:
                raise PermissionError('memory reference is outside the permitted sensitivity scope')
            output.append(memory_id)
        return output

    def _tools(self):
        return getattr(self.executor, 'tools', None)

    def _classify_step(self, item: dict, position: int):
        tool_name = str(item.get('requested_tool') or item.get('tool') or '').strip()
        instruction = str(item.get('instruction') or item.get('description') or '').strip()
        kind = str(item.get('kind') or ('tool' if tool_name else 'reason')).strip().lower()
        if not tool_name:
            raise ValueError(f'plan step {position + 1} requires requested_tool')
        tools = self._tools()
        if tools is None:
            raise RuntimeError('governed tool registry is unavailable')
        try:
            tool = tools.get(tool_name)
        except Exception as exc:
            raise ValueError(f'plan step {position + 1} uses an unavailable tool') from exc
        if getattr(tool, 'prohibited', False):
            raise PermissionError(f'plan step {position + 1} uses a prohibited tool')
        parameters = dict(item.get('parameters') or {})
        self._assert_safe_parameters(parameters)
        sensitivity = str(item.get('sensitivity') or 'internal').strip().lower()
        if sensitivity not in {'public', 'internal', 'sensitive', 'restricted', 'secret'}:
            raise ValueError('unsupported data sensitivity')
        if sensitivity in set(getattr(tool, 'prohibited_data_classifications', ()) or ()):
            raise PermissionError('tool policy prohibits this data classification')
        tools.validate_destination(tool, parameters)
        risk = tools.effective_risk(tool, parameters=parameters, data_classification=sensitivity)
        if int(risk) > int(Risk.READ_ONLY) and not bool(getattr(tool, 'verification_required', False)):
            raise PermissionError('P6 refuses non-read-only delegation without an existing enforced verification contract')
        decision = getattr(tools, 'permissions', None)
        permission = decision.decide(int(risk), confirmed=False) if decision is not None else None
        requires_reauth = bool(getattr(tool, 'requires_reauth', False) or risk == Risk.CRITICAL)
        timeout = max(1, min(int(item.get('timeout_seconds', 120)), 3600))
        return OperationStep(
            id=str(item.get('id') or uuid.uuid4()),
            kind=kind,
            instruction=instruction[:1000],
            consequential=bool(int(risk) >= int(Risk.EXTERNAL_SIDE_EFFECT)),
            status='pending',
            requested_tool=tool_name,
            parameters=parameters,
            risk=risk.name,
            sensitivity=sensitivity,
            approval_required=bool(permission is not None and not permission.allowed),
            requires_reauth=requires_reauth,
            expected_verification='required' if int(risk) > int(Risk.READ_ONLY) else 'read_only_observation',
            timeout_seconds=timeout,
        )

    def _budget_policy(self, supplied: dict | None, *, step_count: int):
        policy = {**self.DEFAULT_BUDGET, **dict(supplied or {})}
        policy['max_retries'] = 0
        policy['owner_override_allowed'] = False
        policy = normalize_policy(policy)
        if step_count > int(policy['max_steps']):
            raise ValueError('operation plan exceeds configured max_steps')
        if step_count > int(policy['max_tool_calls']):
            raise ValueError('operation plan exceeds configured max_tool_calls')
        return policy

    def create_plan(
        self,
        title: str,
        steps: list[dict],
        *,
        owner_id: str = 'owner',
        source_refs: Iterable[str] | None = None,
        memory_ids: Iterable[str] | None = None,
        allowed_sensitivities: set[str] | None = None,
        everyday_item_id: str | None = None,
        budget_policy: dict | None = None,
    ):
        title = str(title or '').strip()
        if not title or not steps:
            raise ValueError('title and steps required')
        if len(steps) > 50:
            raise ValueError('operation plan may contain at most 50 steps')
        if self.executor is None or self.automations is None:
            normalized = [
                OperationStep(
                    str(uuid.uuid4()),
                    str(item.get('kind', 'reason')),
                    str(item.get('instruction', '')).strip(),
                    bool(item.get('consequential', False)),
                )
                for item in steps[:50]
            ]
            plan = {'id': str(uuid.uuid4()), 'title': title, 'status': 'planned', 'steps': [asdict(s) for s in normalized]}
            self._save_plan(plan)
            return plan

        normalized = [self._classify_step(item, index) for index, item in enumerate(steps)]
        policy = self._budget_policy(budget_policy, step_count=len(normalized))
        refs = self._safe_ref_list(source_refs)
        checked_memory = self._memory_ids(memory_ids, allowed_sensitivities=allowed_sensitivities)
        if everyday_item_id:
            if self.everyday is None or not self.everyday.get(everyday_item_id):
                raise KeyError('everyday item not found')
            item = self.everyday.get(everyday_item_id)
            if item.get('status') in getattr(self.everyday, 'TERMINAL_STATES', set()):
                raise ValueError('terminal everyday item cannot start a new operation')
            active = self.operations(status='active', everyday_item_id=everyday_item_id, limit=10)
            if active:
                raise RuntimeError('an active operation already exists for this everyday item')
            refs.append(f'everyday:{everyday_item_id}')
            item_memory = self._memory_ids(item.get('related_memory_ids', []), allowed_sensitivities=allowed_sensitivities)
            checked_memory = list(dict.fromkeys([*checked_memory, *item_memory]))
        plan_id = str(uuid.uuid4())
        plan = {
            'id': plan_id,
            'title': title,
            'owner_id': str(owner_id or 'owner'),
            'status': 'planned',
            'steps': [asdict(step) for step in normalized],
            'allowed_tools': sorted({step.requested_tool for step in normalized if step.requested_tool}),
            'source_refs': list(dict.fromkeys(refs))[:100],
            'memory_ids': checked_memory[:100],
            'everyday_item_id': everyday_item_id,
            'budget_policy': policy,
            'created_at': _utc_now(),
        }
        self._save_plan(plan)
        self._emit('future.operation.planning', plan_id=plan_id, owner_id=plan['owner_id'], step_count=len(normalized))
        return plan

    def create_from_everyday(self, item_id: str, title: str, steps: list[dict], **kwargs):
        if self.everyday is None:
            raise RuntimeError('everyday intelligence is unavailable')
        item = self.everyday.get(item_id)
        if not item:
            raise KeyError('everyday item not found')
        kwargs.setdefault('memory_ids', item.get('related_memory_ids', []))
        kwargs['everyday_item_id'] = item_id
        return self.create_plan(title, steps, **kwargs)

    @staticmethod
    def _risk_summary(plan):
        counts: dict[str, int] = {}
        consequential = 0
        reauth = 0
        for step in plan.get('steps', []):
            risk = str(step.get('risk') or 'READ_ONLY')
            counts[risk] = counts.get(risk, 0) + 1
            consequential += int(bool(step.get('consequential')))
            reauth += int(bool(step.get('requires_reauth')))
        return {'counts': counts, 'consequential_steps': consequential, 'reauth_steps': reauth}
