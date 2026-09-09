import pytest
from crawler.url_utils import normalize_url, is_same_registrable_domain, is_safe_url

def test_normalize_url():
    assert normalize_url("EXAMPLE.COM/") == "https://example.com/"
    assert normalize_url("http://example.com/about/#section") == "http://example.com/about"
    assert normalize_url("https://example.co.uk:443/test/") == "https://example.co.uk/test"

def test_is_same_registrable_domain():
    assert is_same_registrable_domain("https://sub.example.co.uk/page", "https://example.co.uk/about")
    assert is_same_registrable_domain("https://example.com", "https://blog.example.com")
    assert not is_same_registrable_domain("https://example.com", "https://google.com")

def test_ssrf_protection():
    assert not is_safe_url("http://127.0.0.1")
    assert not is_safe_url("http://localhost:8000")
    assert not is_safe_url("http://10.0.0.1")
    assert not is_safe_url("file:///etc/passwd")
    assert is_safe_url("https://example.com")
