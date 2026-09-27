from tools.registry import Tool, Risk


def register(reg, engine):
    reg.register(
        Tool(
            'automation_list',
            'List scheduled automations',
            lambda p: engine.list(),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'automation_create',
            'Create scheduled automation; params: title,prompt,next_run_at,interval_seconds,condition',
            lambda p: {
                'automation_id': engine.create(
                    str(p['title']),
                    str(p['prompt']),
                    str(p['next_run_at']),
                    p.get('interval_seconds'),
                    p.get('condition'),
                )
            },
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'workflow_list',
            'List durable P2.4 workflows and their triggers/steps',
            lambda p: engine.workflows(),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'workflow_runs',
            'Read workflow activity history; params: workflow_id,limit',
            lambda p: engine.runs(p.get('workflow_id'), int(p.get('limit', 100))),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'workflow_create',
            'Create durable workflow; params: title,trigger,steps,next_run_at,interval_seconds',
            lambda p: {
                'workflow_id': engine.create_workflow(
                    str(p['title']),
                    dict(p.get('trigger') or {}),
                    list(p.get('steps') or []),
                    next_run_at=p.get('next_run_at'),
                    interval_seconds=p.get('interval_seconds'),
                )
            },
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'workflow_pause',
            'Pause or resume a workflow; params: workflow_id,paused',
            lambda p: engine.pause_workflow(str(p['workflow_id']), bool(p.get('paused', True))),
            Risk.REVERSIBLE,
        )
    )
    reg.register(
        Tool(
            'workflow_run',
            'Start a workflow manually; params: workflow_id. Underlying steps still use centralized permissions/approvals.',
            lambda p: {'run_id': engine.run_workflow(str(p['workflow_id']), background=True)},
            Risk.EXTERNAL_SIDE_EFFECT,
        )
    )
