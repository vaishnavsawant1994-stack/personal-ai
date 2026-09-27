from __future__ import annotations

from tools.registry import Risk, Tool
from vision.computer_intelligence import ComputerIntelligence


def register(reg, models, settings, *, second_brain=None, events=None):
    computer = ComputerIntelligence(
        models,
        settings.data_dir,
        second_brain=second_brain,
        events=events,
    )
    reg.register(
        Tool(
            'computer_observe',
            'Observe and understand the current screen without acting; params: question,monitor',
            lambda p: computer.observe(
                str(p.get('question', 'Describe the visible screen and actionable UI elements.')),
                int(p.get('monitor', 1)),
            ),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'computer_plan',
            'Create a bounded Observe→Understand→Act→Verify desktop plan without executing it; params: goal,max_steps',
            lambda p: computer.plan(str(p['goal']), max_steps=int(p.get('max_steps', 8))),
            Risk.READ_ONLY,
        )
    )
    reg.register(
        Tool(
            'computer_execute',
            'Execute a bounded, transactional, visually verified desktop task; params: goal,max_steps,monitor. Requires consequential-action authority.',
            lambda p: computer.execute(
                str(p['goal']),
                max_steps=int(p.get('max_steps', 8)),
                monitor=int(p.get('monitor', 1)),
            ),
            Risk.EXTERNAL_SIDE_EFFECT,
        )
    )
    return computer
