from tools.registry import Tool, Risk


def register(reg, store, second_brain=None):
    def remember(p):
        if second_brain is not None:
            from memory.second_brain import MemoryCandidate

            memory_id = second_brain.remember(
                MemoryCandidate(
                    type=str(p.get('type', 'note')),
                    subject=str(p.get('subject', 'note')),
                    content=str(p['content']),
                    source='explicit-user',
                    confidence=float(p.get('confidence', 1.0)),
                    verified=True,
                    tags=list(p.get('tags', [])),
                    importance=float(p.get('importance', 0.7)),
                    sensitivity=str(p.get('sensitivity', 'normal')),
                    occurred_at=p.get('occurred_at'),
                    evidence=list(p.get('evidence') or []),
                    metadata=dict(p.get('metadata') or {}),
                )
            )
        else:
            memory_id = store.remember(
                type=str(p.get('type', 'note')),
                subject=str(p.get('subject', 'note')),
                content=str(p['content']),
                source='explicit-user',
                verified=True,
                tags=list(p.get('tags', [])),
                importance=float(p.get('importance', 0.7)),
                sensitivity=str(p.get('sensitivity', 'normal')),
                occurred_at=p.get('occurred_at'),
                evidence=list(p.get('evidence') or []),
                metadata=dict(p.get('metadata') or {}),
            )
        return {'memory_id': memory_id}

    reg.register(
        Tool(
            'remember',
            'Save verified memory; params: type,subject,content,tags,importance,sensitivity,occurred_at,evidence,metadata',
            remember,
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'search_memory',
            'Search memory; params: query,limit',
            lambda p: second_brain.context(str(p['query']), int(p.get('limit', 20)))
            if second_brain is not None
            else store.search(str(p['query']), int(p.get('limit', 20))),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'memory_temporal',
            'Search memory by time; params: query,start,end,type,limit',
            lambda p: second_brain.temporal(
                str(p.get('query', '')),
                start=p.get('start'),
                end=p.get('end'),
                memory_type=p.get('type'),
                limit=int(p.get('limit', 50)),
            )
            if second_brain is not None
            else store.temporal_search(
                str(p.get('query', '')),
                start=p.get('start'),
                end=p.get('end'),
                memory_type=p.get('type'),
                limit=int(p.get('limit', 50)),
            ),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'memory_detail',
            'Read one memory with salience, usage, relationships and conflicts; params: memory_id',
            lambda p: second_brain.memory_detail(str(p['memory_id']))
            if second_brain is not None
            else store.get(str(p['memory_id'])),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'memory_conflicts',
            'List detected memory conflicts and supersessions',
            lambda p: store.conflicts(int(p.get('limit', 100))),
            Risk.READ_ONLY,
        )
    )
