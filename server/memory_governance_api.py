from __future__ import annotations

from fastapi import APIRouter, HTTPException

from security.request_context import current_trusted_request


def memory_governance_router(runtime):
    router = APIRouter(prefix='/iphone/api/memory/candidates', tags=['memory-governance'])
    registry = runtime['device_registry']
    governed = runtime['second_brain']

    def require_owner(scope: str):
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, 'Trusted owner session required')
        if not registry.is_active(context.device_id):
            raise HTTPException(401, 'Trusted device is revoked')
        if hasattr(registry, 'authorize') and not registry.authorize(context.device_id, scope):
            raise HTTPException(403, f'This device is not permitted to use {scope}')
        return context

    @router.get('')
    def pending_memory_candidates(limit: int = 100):
        require_owner('memory:read')
        candidates = getattr(governed, 'candidates', None)
        if not callable(candidates):
            raise HTTPException(503, 'Governed Memory candidate review is unavailable')
        return {'candidates': candidates(status='pending', limit=max(1, min(int(limit), 500)))}

    @router.post('/{candidate_id}/approve')
    def approve_memory_candidate(candidate_id: str):
        context = require_owner('memory:write')
        approve = getattr(governed, 'approve_candidate', None)
        if not callable(approve):
            raise HTTPException(503, 'Governed Memory candidate review is unavailable')
        try:
            memory_id = approve(candidate_id, owner_id='owner')
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        detail = governed.memory_detail(memory_id)
        runtime['memory'].audit(
            'owner-product',
            'memory.candidate.approved',
            {'device_id': context.device_id, 'candidate_id': candidate_id, 'memory_id': memory_id},
        )
        return {'ok': True, 'memory_id': memory_id, 'memory': detail}

    @router.delete('/{candidate_id}')
    def reject_memory_candidate(candidate_id: str):
        context = require_owner('memory:write')
        reject = getattr(governed, 'reject_candidate', None)
        if not callable(reject):
            raise HTTPException(503, 'Governed Memory candidate review is unavailable')
        if not reject(candidate_id, owner_id='owner'):
            raise HTTPException(404, 'Pending memory candidate not found')
        runtime['memory'].audit(
            'owner-product',
            'memory.candidate.rejected',
            {'device_id': context.device_id, 'candidate_id': candidate_id},
        )
        return {'ok': True, 'candidate_id': candidate_id}

    return router
