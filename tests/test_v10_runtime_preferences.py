from types import SimpleNamespace
import pytest
from tools.registry import ToolRegistry,Tool,Risk
from voice.wake_phrase import WakePhraseGate

def test_runtime_autonomy_changes_are_validated():
    reg=ToolRegistry(SimpleNamespace(autonomy_mode='ask'));side=Tool('side','side',lambda p:True,Risk.EXTERNAL_SIDE_EFFECT);reg.register(side)
    assert reg.authorize(side).allowed is False
    reg.set_autonomy_mode('observe');assert reg.autonomy_mode=='observe';assert reg.authorize(side).allowed is False
    reg.set_autonomy_mode('act');assert reg.autonomy_mode=='act';assert reg.authorize(side).allowed is False
    with pytest.raises(ValueError):reg.set_autonomy_mode('unsafe')

def test_configurable_wake_phrase_works():
    gate=WakePhraseGate(phrases=('hello personal',));result=gate.accept('Hello Personal, summarize my day',now=10);assert result['triggered'] is True;assert result['command']=='summarize my day'
    gate.phrases=('computer',);gate.reset();result=gate.accept('computer open memory',now=20);assert result['triggered'] is True;assert result['command']=='open memory'
