from __future__ import annotations

from tools.registry import Risk, Tool


def register(reg, engine):
    reg.register(
        Tool(
            'proactive_consider',
            'Evaluate a normalized event through the calm Attention & Relevance Engine; params: source,payload,context',
            lambda p: engine.consider(
                str(p.get('source', 'manual')),
                dict(p.get('payload') or {}),
                context=dict(p.get('context') or {}),
            ).__dict__,
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'proactive_history',
            'Read recent proactive attention decisions; params: limit',
            lambda p: engine.history(int(p.get('limit', 100))),
            Risk.READ_ONLY,
        )
    )
