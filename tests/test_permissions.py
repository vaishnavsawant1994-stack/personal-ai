from core.permissions import PermissionEngine, ActionRisk

def test_ask_blocks_side_effects():
    p=PermissionEngine("ask")
    assert p.decide(ActionRisk.READ_ONLY).allowed
    d=p.decide(ActionRisk.EXTERNAL_SIDE_EFFECT)
    assert not d.allowed and d.requires_confirmation

def test_act_still_blocks_destructive_without_confirmation():
    p=PermissionEngine("act")
    assert p.decide(ActionRisk.REVERSIBLE).allowed
    assert not p.decide(ActionRisk.DESTRUCTIVE).allowed
    assert p.decide(ActionRisk.DESTRUCTIVE,confirmed=True).allowed
