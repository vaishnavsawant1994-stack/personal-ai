import pytest

from tools.web import _safe_web_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://127.0.0.1/admin",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "https://user:password@example.com/",
])
def test_legacy_web_open_rejects_unsafe_or_private_destinations(url):
    with pytest.raises(ValueError):
        _safe_web_url(url)


def test_legacy_web_open_accepts_public_https_destination():
    assert _safe_web_url("https://example.com/path") == "https://example.com/path"
