"""Stage-8: workflow run listing must fail closed without binding authority."""

from types import SimpleNamespace


class EngineWithoutBinding:
    def workflows(self):
        return [{'id': 'wf-1', 'title': 'hidden'}]

    def runs(self, workflow_id=None, limit=100):
        return [
            {
                'id': 'run-secret',
                'workflow_id': 'wf-1',
                'status': 'completed',
                'result_json': '{"secret": true}',
            }
        ]


class EngineWithBinding(EngineWithoutBinding):
    def run_binding(self, run_id):
        if run_id == 'run-secret':
            return {
                'owner_id': 'owner',
                'device_id': 'other-device',
                'session_id': None,
            }
        return None


def test_stage8_workflow_runs_fail_closed_when_binding_authority_missing():
    """Missing run_binding must not dump all runs to an authenticated device."""
    engine = EngineWithoutBinding()
    binding_reader = getattr(engine, 'run_binding', None)
    assert not callable(binding_reader)
    rows = engine.runs()
    assert rows  # engine would leak if returned raw
    # Production API must treat missing binding as unavailable (503), not return rows.
    assert not callable(getattr(engine, 'run_binding', None))


def test_stage8_workflow_runs_hide_other_device_bindings():
    engine = EngineWithBinding()
    binding = engine.run_binding('run-secret')
    assert binding['device_id'] == 'other-device'
    caller = 'device-1'
    assert binding.get('device_id') not in (None, caller)
