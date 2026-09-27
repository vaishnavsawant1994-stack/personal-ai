import pytest
from security.vault import SecretVault
def test_vault_encrypts_and_rotates(tmp_path):
    p=tmp_path/'v.json'; v=SecretVault(p,'old'); v.set('token','secret-value'); assert 'secret-value' not in p.read_text(); assert SecretVault(p,'old').get('token')=='secret-value'; v.rotate_password('new'); assert SecretVault(p,'new').get('token')=='secret-value'
    with pytest.raises(Exception): SecretVault(p,'old')
