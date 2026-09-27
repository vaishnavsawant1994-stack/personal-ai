from __future__ import annotations
import base64
import pytest
from security.keychain import KeychainUnavailable,RootKeyStore


def test_environment_root_key_is_used_without_os_keyring(monkeypatch):
    key=b'k'*32
    monkeypatch.setenv('PERSONAL_AI_ROOT_KEY',base64.b64encode(key).decode())
    store=RootKeyStore()
    monkeypatch.setattr(store,'_kr',lambda: (_ for _ in ()).throw(RuntimeError('no keyring')))
    assert store.get()==key
    assert store.get_or_create()==key


def test_environment_root_key_requires_exact_32_bytes(monkeypatch):
    monkeypatch.setenv('PERSONAL_AI_ROOT_KEY',base64.b64encode(b'short').decode())
    with pytest.raises(KeychainUnavailable):
        RootKeyStore().get()


def test_environment_root_key_cannot_be_rotated_in_process(monkeypatch):
    monkeypatch.setenv('PERSONAL_AI_ROOT_KEY',base64.b64encode(b'x'*32).decode())
    with pytest.raises(KeychainUnavailable):
        RootKeyStore().rotate()
