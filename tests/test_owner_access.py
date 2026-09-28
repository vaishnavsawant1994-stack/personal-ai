from security.owner_access import OwnerAccessStore


def test_password_and_recovery_codes_are_durable_and_one_use(tmp_path):
    path = tmp_path / 'owner-access.sqlite3'
    access = OwnerAccessStore(path)
    assert access.password_configured() is False
    access.set_password('a-secure-owner-password')
    codes = access.regenerate_recovery_codes()

    reopened = OwnerAccessStore(path)
    assert reopened.verify_password('a-secure-owner-password') is True
    assert reopened.verify_password('incorrect-password') is False
    assert reopened.recovery_codes_remaining() == 8
    assert reopened.consume_recovery_code(codes[0].lower()) is True
    assert reopened.consume_recovery_code(codes[0]) is False
    assert reopened.recovery_codes_remaining() == 7


def test_password_rejects_short_values(tmp_path):
    access = OwnerAccessStore(tmp_path / 'owner-access.sqlite3')
    try:
        access.set_password('too-short')
    except ValueError as exc:
        assert '12 characters' in str(exc)
    else:
        raise AssertionError('short owner password was accepted')


def test_challenges_are_scoped_one_use_and_expire(tmp_path):
    access = OwnerAccessStore(tmp_path / 'owner-access.sqlite3')
    challenge_id = access.create_challenge(
        'registration', b'challenge', 'testserver', 'https://testserver', device_id='device-1', ttl=30,
    )
    assert access.consume_challenge(challenge_id, 'registration', device_id='device-2') is None
    assert access.consume_challenge(challenge_id, 'registration', device_id='device-1') is None


def test_passkey_metadata_persists_without_private_key_material(tmp_path):
    path = tmp_path / 'owner-access.sqlite3'
    access = OwnerAccessStore(path)
    access.save_passkey(b'credential', b'public-key', 4, 'Owner Face ID', '["internal"]')
    reopened = OwnerAccessStore(path)
    listed = reopened.passkeys()
    assert listed[0]['name'] == 'Owner Face ID'
    assert 'public_key' not in listed[0]
    stored = reopened.passkey(b'credential')
    assert stored['public_key'] == b'public-key'
    reopened.use_passkey(b'credential', 5)
    assert reopened.passkey(b'credential')['sign_count'] == 5
