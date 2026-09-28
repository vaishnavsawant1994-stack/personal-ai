import time
from security.policy_gateway import DecisionKind,PolicyGateway,PolicyOperation


def _op(**changes):
    values=dict(operation='read',owner_id='owner',device_id='d',session_id='s',security_epoch=1,target_type='destination',target_identity={'identity':'x'},destination='x',data_classification='public');values.update(changes);return PolicyOperation(**values)

def _add(gateway,**changes):
    values=dict(owner_id='owner',target_type='destination',target_identity={'identity':'x'},allowed_operations=['read'],security_epoch=1,reauthenticated=True);values.update(changes);return gateway.add_policy(**values)

def test_owner_can_disable_and_reenable_policy_with_reauth(tmp_path):
    g=PolicyGateway(tmp_path/'toggle.db');p=_add(g);assert g.evaluate(_op()).allowed
    assert g.set_policy_active(p['policy_id'],owner_id='owner',enabled=False,reauthenticated=True)
    assert g.evaluate(_op()).decision is DecisionKind.DENY
    assert g.set_policy_active(p['policy_id'],owner_id='owner',enabled=True,reauthenticated=True)
    assert g.evaluate(_op()).allowed

def test_trusted_action_binding_covers_policy_observation_parameters_and_use_limit(tmp_path):
    g=PolicyGateway(tmp_path/'bind.db');_add(g,approval_rule='always',max_uses=1)
    operation=_op(observation_id='obs-1',observation_digest='obs-digest',parameters={'amount':10})
    requested=g.evaluate(operation);assert requested.decision is DecisionKind.APPROVAL_REQUIRED
    allowed=g.evaluate(operation,approved=True,expected_policy_digest=requested.policy_digest)
    binding=g.trusted_action_binding(operation,allowed,expires_at=time.time()+30)
    assert binding['policy_digest']==allowed.policy_digest
    assert binding['observation_id']=='obs-1' and binding['observation_digest']=='obs-digest'
    assert binding['parameter_digest']==operation.parameter_digest()
    assert binding['owner_id']=='owner' and binding['device_id']=='d' and binding['session_id']=='s'
    assert binding['security_epoch']==1 and binding['maximum_uses']==1
