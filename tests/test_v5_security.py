from integrations.permissions import effect_for
from desktop.transactions import DesktopTransaction
from devices.gateway import DeviceCommand

def test_integration_effects():
    assert effect_for('gmail','read_mail')=='read';assert effect_for('gmail','send_mail')=='external';assert effect_for('calendar','delete_event')=='destructive'
def test_transaction_defaults():
    tx=DesktopTransaction();assert tx.id and tx.actions==[] and not tx.committed
def test_device_command_shape():
    c=DeviceCommand('battery',{},'r1');assert c.action=='battery' and c.request_id=='r1'
