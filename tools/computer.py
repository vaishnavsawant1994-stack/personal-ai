from __future__ import annotations

from tools.registry import Risk, Tool
from vision.computer_intelligence import ComputerIntelligence


def register(reg, models, settings, *, second_brain=None, events=None):
    computer = ComputerIntelligence(models, settings.data_dir, second_brain=second_brain, events=events, emergency_stop=lambda: bool(getattr(reg, 'emergency_stop', False)), browser_session=getattr(reg, '_persistent_browser', None))
    reg.register(Tool('computer_observe','Observe and understand the current screen without acting; params: question,monitor',lambda p:computer.observe(str(p.get('question','Describe the visible screen and actionable UI elements.')),int(p.get('monitor',1))),Risk.READ_ONLY))
    reg.register(Tool('computer_plan','Create a bounded Observe→Understand→Act→Verify desktop plan without executing it; params: goal,max_steps',lambda p:computer.plan(str(p['goal']),max_steps=int(p.get('max_steps',8))),Risk.READ_ONLY))
    reg.register(Tool('computer_execute','Execute only the exact Personal AI prepared, owner-approved, observation-bound, durable and verified computer plan; params: goal,max_steps,monitor,timeout_seconds.',lambda p:computer.execute_prepared(p),Risk.EXTERNAL_SIDE_EFFECT,rollback_description='No generic automatic rollback is promised. Individual reversible desktop actions may be compensated only when technically safe and separately authorized.',verification_required=True,requires_reauth=True,minimum_risk=Risk.EXTERNAL_SIDE_EFFECT,prepare=computer.prepare_execution,on_reject=computer.reject_execution,requires_trusted_context=True))
    return computer
