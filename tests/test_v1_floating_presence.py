from __future__ import annotations

from core.events import EventBus
from core.runtime_state import RuntimeState
from desktop.floating_presence import PresenceController


def test_presence_tracks_only_canonical_runtime_state(tmp_path):
    events = EventBus()
    controller = PresenceController(events, tmp_path / 'presence.json')
    events.emit('state', state='active')
    events.emit('state', state='listening')
    assert controller.state is RuntimeState.LISTENING
    controller.close()


def test_presence_position_is_clamped_inside_available_screen():
    # Clamp only positions that would make the surface inaccessible. A valid
    # owner-selected position must remain unchanged rather than snapping to an edge.
    clamp = PresenceController.clamp_position
    assert clamp(-500, 9000, left=0, top=0, right=1920, bottom=1080, width=118, height=118) == (0, 962)
    assert clamp(2500, -20, left=1920, top=0, right=3840, bottom=2160, width=330, height=230) == (2500, 0)


def test_presence_clamp_preserves_valid_positions_and_all_edges():
    clamp = PresenceController.clamp_position
    kwargs = dict(left=0, top=0, right=1920, bottom=1080, width=118, height=118)
    assert clamp(-1, 100, **kwargs) == (0, 100)
    assert clamp(0, 100, **kwargs) == (0, 100)
    assert clamp(700, 400, **kwargs) == (700, 400)
    assert clamp(1802, 962, **kwargs) == (1802, 962)
    assert clamp(1803, 400, **kwargs) == (1802, 400)
    assert clamp(700, -1, **kwargs) == (700, 0)
    assert clamp(700, 500, **kwargs) == (700, 500)
    assert clamp(700, 963, **kwargs) == (700, 962)


def test_presence_clamp_handles_offset_and_negative_coordinate_monitors():
    clamp = PresenceController.clamp_position
    # Secondary monitor to the right of the primary.
    assert clamp(2500, 500, left=1920, top=0, right=3840, bottom=2160, width=330, height=230) == (2500, 500)
    assert clamp(4000, 500, left=1920, top=0, right=3840, bottom=2160, width=330, height=230) == (3510, 500)
    # Monitor to the left of the primary.
    assert clamp(-1500, 300, left=-1920, top=0, right=0, bottom=1080, width=118, height=118) == (-1500, 300)
    assert clamp(-3000, 300, left=-1920, top=0, right=0, bottom=1080, width=118, height=118) == (-1920, 300)
    # Monitor above the primary.
    assert clamp(400, -700, left=0, top=-1080, right=1920, bottom=0, width=118, height=118) == (400, -700)
    assert clamp(400, -1400, left=0, top=-1080, right=1920, bottom=0, width=118, height=118) == (400, -1080)


def test_presence_clamp_accounts_for_compact_and_expanded_surface_sizes():
    clamp = PresenceController.clamp_position
    # The same saved top-left can be valid for compact mode but must move inward
    # after expansion so the owner can still reach the complete panel.
    assert clamp(1800, 850, left=0, top=0, right=1920, bottom=1080, width=118, height=118) == (1800, 850)
    assert clamp(1800, 850, left=0, top=0, right=1920, bottom=1080, width=330, height=230) == (1590, 850)


def test_presence_position_survives_restart(tmp_path):
    path = tmp_path / 'presence.json'
    first = PresenceController(EventBus(), path)
    first.save_position(321, 654)
    first.close()
    second = PresenceController(EventBus(), path)
    assert second.position == (321, 654)
    second.close()


def test_presence_does_not_invent_state_from_position_or_panel_state(tmp_path):
    events = EventBus()
    controller = PresenceController(events, tmp_path / 'presence.json')
    controller.save_position(10, 20)
    assert controller.state is RuntimeState.IDLE
    events.runtime_state.transition(RuntimeState.BACKGROUND, reason='real_background_work')
    assert controller.state is RuntimeState.BACKGROUND
    controller.close()
