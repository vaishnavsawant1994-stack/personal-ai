import base64,json,pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from updates.signed_updater import SignedUpdater,UpdateVerificationError
def test_manifest_signature(tmp_path):
    priv=Ed25519PrivateKey.generate(); pub=priv.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw); u=SignedUpdater(base64.b64encode(pub).decode(),tmp_path/'app'); m=json.dumps({'version':'1'}).encode(); sig=base64.b64encode(priv.sign(m)).decode(); assert u.verify_manifest(m,sig)['version']=='1'
    with pytest.raises(UpdateVerificationError):u.verify_manifest(m+b'x',sig)
