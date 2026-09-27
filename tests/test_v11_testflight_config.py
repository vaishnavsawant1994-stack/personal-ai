from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ios_distribution_workflow_is_manual_and_fail_closed():
    text = (ROOT / '.github/workflows/ios-testflight.yml').read_text()
    assert 'workflow_dispatch:' in text
    assert 'if: ${{ inputs.upload }}' in text
    assert 'environment: apple-distribution' in text
    assert 'Missing required secret:' in text
    assert 'xcrun altool --upload-app' in text
    assert 'SDK_MAJOR' in text and '-ge 26' in text


def test_testflight_secrets_are_not_literal_values():
    text = (ROOT / '.github/workflows/ios-testflight.yml').read_text()
    required = [
        'APPLE_TEAM_ID', 'APP_STORE_CONNECT_KEY_ID', 'APP_STORE_CONNECT_ISSUER_ID',
        'APP_STORE_CONNECT_PRIVATE_KEY_B64', 'IOS_DISTRIBUTION_CERT_P12_B64',
        'IOS_DISTRIBUTION_CERT_PASSWORD', 'IOS_APPSTORE_PROFILE_B64'
    ]
    for name in required:
        assert ('secrets.' + name) in text


def test_ios_release_identity_is_stable():
    text = (ROOT / 'ios-companion/project.yml').read_text()
    assert 'PRODUCT_BUNDLE_IDENTIFIER: ai.personal.companion.ios' in text
    assert 'MARKETING_VERSION: 0.1.0' in text
    assert 'CURRENT_PROJECT_VERSION: 1' in text
