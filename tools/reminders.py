from datetime import datetime, timezone
import json
import uuid

from tools.registry import Tool, Risk


def register(reg, store):
    def everyday():
        return getattr(store, 'everyday_intelligence', None)

    def create(p):
        lifecycle = everyday()
        if lifecycle is not None:
            item_id = lifecycle.add(
                'reminder',
                str(p['title']),
                due_at=str(p.get('due_at') or '') or None,
                priority=float(p.get('priority', .5)),
                context=str(p.get('context') or ''),
                source='tool:create_reminder',
                timezone_name=str(p.get('timezone') or lifecycle.timezone_name),
                related_memory_ids=list(p.get('related_memory_ids') or []),
                evidence=list(p.get('evidence') or []),
            )
            return {'ok': True, 'task_id': item_id, 'authority': 'everyday_intelligence'}

        title = str(p['title'])
        due = str(p.get('due_at', ''))
        item_id = str(uuid.uuid4())
        with store.lock, store.con() as c:
            c.execute(
                'INSERT INTO tasks VALUES(?,?,?,?,?,?)',
                (item_id, title, 'pending', due, json.dumps(p.get('payload', {})), datetime.now(timezone.utc).isoformat()),
            )
        return {'ok': True, 'task_id': item_id, 'authority': 'legacy_fallback'}

    def complete(p):
        lifecycle = everyday()
        if lifecycle is None:
            return {'ok': False, 'error': 'reminder lifecycle unavailable'}
        return {'ok': lifecycle.complete(str(p['task_id'])), 'task_id': str(p['task_id'])}

    def snooze(p):
        lifecycle = everyday()
        if lifecycle is None:
            return {'ok': False, 'error': 'reminder lifecycle unavailable'}
        return {
            'ok': lifecycle.snooze(str(p['task_id']), str(p['until']), timezone_name=p.get('timezone')),
            'task_id': str(p['task_id']),
        }

    def cancel(p):
        lifecycle = everyday()
        if lifecycle is None:
            return {'ok': False, 'error': 'reminder lifecycle unavailable'}
        return {'ok': lifecycle.cancel(str(p['task_id'])), 'task_id': str(p['task_id'])}

    reg.register(Tool('create_reminder', 'Create reminder/task; params: title,due_at,priority,context,timezone,related_memory_ids,evidence', create, Risk.REVERSIBLE))
    reg.register(Tool('complete_reminder', 'Complete reminder/task; params: task_id', complete, Risk.REVERSIBLE))
    reg.register(Tool('snooze_reminder', 'Snooze reminder/task; params: task_id,until,timezone', snooze, Risk.REVERSIBLE))
    reg.register(Tool('cancel_reminder', 'Cancel reminder/task; params: task_id', cancel, Risk.REVERSIBLE))
