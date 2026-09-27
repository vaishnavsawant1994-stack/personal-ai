from __future__ import annotations

from tools.registry import Risk, Tool


def register(reg, service):
    reg.register(
        Tool(
            'continuity_resume',
            'Resume the active Personal AI context for a trusted device; params: device_id,thread_id',
            lambda p: service.resume(str(p['device_id']), thread_id=p.get('thread_id')),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'continuity_update_context',
            'Update the shared active context for a continuity thread; params: thread_id,patch',
            lambda p: service.update_context(str(p['thread_id']), dict(p.get('patch') or {})),
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'continuity_handoff',
            'Hand off an active Personal AI thread between trusted devices; params: thread_id,from_device,to_device',
            lambda p: service.handoff(
                str(p['thread_id']),
                from_device=p.get('from_device'),
                to_device=str(p['to_device']),
            ),
            Risk.REVERSIBLE,
        )
    )
