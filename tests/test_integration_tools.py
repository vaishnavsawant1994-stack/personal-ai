from types import SimpleNamespace

from tools.builtins import register_builtin_tools
from tools.registry import Risk, ToolRegistry


class Gmail:
    def list_messages(self, **kwargs):
        return kwargs

    def get_message(self, message_id, format='metadata'):
        return {'id': message_id, 'format': format}

    def send_raw(self, raw):
        return {'sent': True, 'raw': raw}


class Calendar:
    def list_events(self, calendar_id, **kwargs):
        return {'calendar_id': calendar_id, **kwargs}

    def create_event(self, event, calendar_id):
        return {'event': event, 'calendar_id': calendar_id}

    def update_event(self, event_id, event, calendar_id):
        return {'event_id': event_id, 'event': event, 'calendar_id': calendar_id}

    def delete_event(self, event_id, calendar_id):
        return {'event_id': event_id, 'calendar_id': calendar_id}


class Memory:
    pass


def test_connected_apps_become_governed_tools(tmp_path):
    registry = ToolRegistry(SimpleNamespace(autonomy_mode='ask'))
    register_builtin_tools(
        registry,
        Memory(),
        SimpleNamespace(data_dir=tmp_path, browser_headless=True),
        integration_adapters={'gmail': Gmail(), 'calendar': Calendar()},
    )

    assert registry.get('gmail_list_messages').risk == Risk.READ_ONLY
    assert registry.get('gmail_send_message').risk == Risk.EXTERNAL_SIDE_EFFECT
    assert registry.get('calendar_delete_event').risk == Risk.DESTRUCTIVE
    assert registry.automatic(registry.get('gmail_list_messages')) is True
    assert registry.automatic(registry.get('gmail_send_message')) is False

    sent = registry.get('gmail_send_message').handler({
        'to': 'owner@example.com',
        'subject': 'Update',
        'body': 'Workflow complete',
    })
    assert sent['sent'] is True
    assert 'owner@example.com' not in sent['raw']
