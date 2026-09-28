"""Approve a browser navigation before the browser follows any redirect."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin

from security.policy_targets import TargetValidationError, domain_rule_matches, normalize_origin

MAX_REDIRECTS = 5
_REDIRECTS = {301, 302, 303, 307, 308}
_FORBIDDEN_HEADERS = {'cookie', 'authorization', 'proxy-authorization'}


def _private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def default_resolve(host: str) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise TargetValidationError('domain_not_allowed', 'Destination hostname could not be resolved.') from exc
    addresses = []
    for row in rows:
        address = row[4][0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise TargetValidationError('domain_not_allowed', 'Destination hostname could not be resolved.')
    return addresses


def default_fetch(url: str):
    """Read one response without following redirects or sending browser credentials."""
    import httpx

    with httpx.Client(follow_redirects=False, timeout=5.0, trust_env=False) as client:
        response = client.get(url)
    return response.status_code, response.headers.get('location'), dict(response.request.headers)


def _matching_rule(url: str, rules: list[dict]) -> dict:
    for rule in rules:
        try:
            matched, _origin = domain_rule_matches(rule, url)
        except TargetValidationError:
            continue
        if matched:
            return rule
    raise TargetValidationError('redirect_not_allowed', 'Redirect left the approved origin.')


def _assert_hop(url: str, start: str, rules: list[dict], resolve_host) -> None:
    rule = _matching_rule(url, rules)
    origin = normalize_origin(
        url,
        allow_ip_literal=bool(rule.get('allow_ip_literal', False)),
        allow_private_network=bool(rule.get('allow_private_network', False)),
    )
    start_origin = normalize_origin(start)
    if start_origin.scheme == 'https' and origin.scheme != 'https':
        raise TargetValidationError('redirect_not_allowed', 'HTTPS navigation cannot be downgraded.')
    if origin.is_ip_literal and not rule.get('allow_ip_literal', False):
        raise TargetValidationError('redirect_not_allowed', 'Redirect to an IP literal is not approved.')
    addresses = resolve_host(origin.host) if not origin.is_ip_literal else [origin.host]
    if any(_private_ip(address) for address in addresses) and not rule.get('allow_private_network', False):
        raise TargetValidationError('redirect_not_allowed', 'Redirect resolves to a private or local address.')


def resolve_navigation(start_url: str, *, rules: list[dict], fetch=None, resolve_host=None, max_redirects: int = MAX_REDIRECTS) -> str:
    """Return the final approved URL. Raise before a rejected hop is requested."""
    fetch = fetch or default_fetch
    resolve_host = resolve_host or default_resolve
    current = str(start_url)
    for hop in range(max_redirects + 1):
        _assert_hop(current, start_url, rules, resolve_host)
        status, location, headers = fetch(current)
        for name in headers or {}:
            if str(name).lower() in _FORBIDDEN_HEADERS:
                raise TargetValidationError('redirect_not_allowed', 'Redirect probe forwarded a credential header.')
        if int(status) not in _REDIRECTS:
            if 200 <= int(status) < 400:
                return current
            raise TargetValidationError('redirect_not_allowed', 'Navigation target did not respond safely.')
        if hop == max_redirects or not location:
            raise TargetValidationError('redirect_not_allowed', 'Redirect chain was not approved.')
        current = urljoin(current, str(location))
    raise TargetValidationError('redirect_not_allowed', 'Redirect chain was not approved.')
