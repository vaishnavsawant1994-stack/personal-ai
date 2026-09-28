"""F4: the browser must not follow an unapproved redirect."""

from __future__ import annotations

import pytest

from browser.safe_operator import BrowserAction, SafeBrowserOperator
from desktop.operator_transactions import OperatorBinding, OperatorTransactionStore
from security.navigation_guard import resolve_navigation
from security.policy_gateway import PolicyGateway
from security.policy_targets import TargetValidationError
from tests.test_w74_safe_browser_operator import FakeBrowser, obs
import browser.safe_operator as operator_module


@pytest.fixture
def env(tmp_path, monkeypatch):
    browser = FakeBrowser()
    policy = PolicyGateway(tmp_path / 'policy.db')
    transactions = OperatorTransactionStore(tmp_path / 'tx.db')
    binding = OperatorBinding('owner', 'device', 'session', 7)
    policy.add_policy(
        owner_id='owner',
        target_type='domain',
        target_identity={'scheme': 'https', 'host': 'example.com', 'port': 443},
        allowed_operations=['navigate', 'read'],
        security_epoch=7,
        reauthenticated=True,
    )
    monkeypatch.setattr(operator_module, 'observe_page', lambda page: obs(page))
    operator = SafeBrowserOperator(browser, policy, transactions, binding)
    operator.redirect_fetch = lambda url: (200, None, {})
    operator.resolve_host = lambda host: ['93.184.216.34']
    return operator


def _script(chain):
    calls = []

    def fetch(url):
        calls.append(url)
        status, location = chain.get(url, (200, None))
        return status, location, {}

    return calls, fetch


def test_same_origin_redirect_opens_only_the_final_url(env):
    op = env
    calls, fetch = _script({
        'https://example.com/start': (302, 'https://example.com/landed'),
        'https://example.com/landed': (200, None),
    })
    op.redirect_fetch = fetch
    result = op.execute(BrowserAction('open_url', 'tx-ok', url='https://example.com/start'))
    assert result.status == 'completed'
    assert op.browser.page.url == 'https://example.com/landed'
    assert calls == ['https://example.com/start', 'https://example.com/landed']


def test_cross_origin_redirect_is_not_requested(env):
    op = env
    calls, fetch = _script({'https://example.com/start': (302, 'https://evil.test/steal')})
    op.redirect_fetch = fetch
    result = op.execute(BrowserAction('open_url', 'tx-cross', url='https://example.com/start', parameters={'final_rule': {'scheme': 'https', 'host': 'evil.test'}}))
    assert result.status == 'denied' and result.reason_code == 'redirect_not_allowed'
    assert calls == ['https://example.com/start']
    assert op.browser.page.url == 'https://example.com/start'
    assert '-nav' not in op.browser.page.dom


def test_https_downgrade_and_private_redirect_are_not_requested(env):
    op = env
    for location in ('http://example.com/plain', 'http://127.0.0.1/admin', 'http://169.254.169.254/latest/meta-data/', 'http://10.1.1.1/'):
        calls, fetch = _script({'https://example.com/start': (302, location)})
        op.redirect_fetch = fetch
        result = op.execute(BrowserAction('open_url', f'tx-{location}', url='https://example.com/start'))
        assert result.status == 'denied' and result.reason_code == 'redirect_not_allowed'
        assert calls == ['https://example.com/start']
        assert '-nav' not in op.browser.page.dom


def test_long_redirect_chain_stops_before_the_browser_moves(env):
    op = env
    chain = {f'https://example.com/{index}': (302, f'https://example.com/{index + 1}') for index in range(8)}
    calls, fetch = _script(chain)
    op.redirect_fetch = fetch
    result = op.execute(BrowserAction('open_url', 'tx-chain', url='https://example.com/0'))
    assert result.status == 'denied' and result.reason_code == 'redirect_not_allowed'
    assert len(calls) <= 6
    assert '-nav' not in op.browser.page.dom


def test_dns_rebinding_to_loopback_is_not_requested(env):
    op = env
    calls, fetch = _script({})
    op.redirect_fetch = fetch
    op.resolve_host = lambda host: ['127.0.0.1']
    result = op.execute(BrowserAction('open_url', 'tx-dns', url='https://example.com/start'))
    assert result.status == 'denied' and result.reason_code == 'redirect_not_allowed'
    assert calls == []
    assert '-nav' not in op.browser.page.dom


def test_credential_header_on_the_probe_is_rejected(env):
    op = env

    def fetch(url):
        return 200, None, {'Authorization': 'Bearer secret'}

    op.redirect_fetch = fetch
    result = op.execute(BrowserAction('open_url', 'tx-cred-header', url='https://example.com/start'))
    assert result.status == 'denied' and result.reason_code == 'redirect_not_allowed'
    assert '-nav' not in op.browser.page.dom


def test_resolve_navigation_rejects_a_caller_supplied_bypass():
    calls = []

    def fetch(url):
        calls.append(url)
        return 302, 'https://evil.test/', {}

    with pytest.raises(TargetValidationError):
        resolve_navigation(
            'https://example.com/start',
            rules=[{'scheme': 'https', 'host': 'example.com', 'port': 443}],
            fetch=fetch,
            resolve_host=lambda host: ['93.184.216.34'],
        )
    assert calls == ['https://example.com/start']
