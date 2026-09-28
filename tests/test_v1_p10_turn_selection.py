from __future__ import annotations

from core.p10_turn_selection import P10TurnSelector


def test_simple_questions_do_not_enter_p10():
    selector = P10TurnSelector()
    for text in ('What is FOIR?', 'Explain this document', 'Who is the CEO?', 'Tell me what you remember about Project X'):
        assert selector.select(text).use_p10 is False


def test_basic_single_action_does_not_force_autonomous_planning():
    selector = P10TurnSelector()
    assert selector.select('Send this email to the address I provided').use_p10 is False


def test_multi_step_delegated_work_selects_p10():
    selector = P10TurnSelector()
    result = selector.select('Handle this for me: first research the options, then compare them, then prepare the final result.')
    assert result.use_p10 is True
    assert 'multi_step_language' in result.signals
    assert 'delegated_work' in result.signals


def test_background_or_agent_coordination_selects_p10():
    selector = P10TurnSelector()
    assert selector.select('Keep working in the background and coordinate agents for this workflow').use_p10 is True
    assert selector.select('Monitor this and tell me when the condition happens').use_p10 is True


def test_multiple_governed_actions_select_p10_even_without_magic_phrase():
    selector = P10TurnSelector()
    result = selector.select('Process the request', requested_actions=3)
    assert result.use_p10 is True


def test_model_advisory_cannot_grant_p10_authority():
    selector = P10TurnSelector()
    base = selector.select('What is the weather policy?')
    advised = selector.apply_advisory(base, model_suggests_p10=True)
    assert base.use_p10 is False
    assert advised.use_p10 is False
    assert advised.advisory_only is True


def test_model_advisory_cannot_disable_deterministically_selected_p10():
    selector = P10TurnSelector()
    base = selector.select('Coordinate agents and keep working in the background')
    advised = selector.apply_advisory(base, model_suggests_p10=False)
    assert base.use_p10 is True
    assert advised.use_p10 is True
