import pytest

from app.core.url_safety import (
    UnsafeWebhookURLError,
    build_pinned_request_target,
    resolve_public_address,
    validate_webhook_url_syntax,
)


def test_syntax_check_rejects_non_https_schemes():
    for url in ("http://example.com", "ftp://example.com", "file:///etc/passwd"):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url_syntax(url)


def test_syntax_check_requires_hostname():
    with pytest.raises(UnsafeWebhookURLError):
        validate_webhook_url_syntax("https:///no-host")


def test_syntax_check_accepts_valid_https_url():
    assert validate_webhook_url_syntax("https://example.com/hook") == "https://example.com/hook"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://127.63.0.1/hook",
        "https://localhost/hook",
        "https://10.0.0.1/hook",
        "https://10.255.255.255/hook",
        "https://172.16.0.1/hook",
        "https://172.31.255.255/hook",
        "https://192.168.0.1/hook",
        "https://192.168.255.255/hook",
        "https://169.254.169.254/hook",
        "https://0.0.0.0/hook",
        "https://224.0.0.1/hook",
        "https://[::1]/hook",
        "https://[fe80::1]/hook",
        "https://[fd00::1]/hook",
        "https://[fc00::1]/hook",
        "https://[ff02::1]/hook",
        "https://internal-service.test/hook",
        "https://metadata.test/hook",
        "https://mixed-address.test/hook",
    ],
)
async def test_resolve_public_address_rejects_unsafe_destinations(url, fake_dns_for_webhook_safety):
    with pytest.raises(UnsafeWebhookURLError):
        await resolve_public_address(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/hook",
        "https://public-webhook.test/hook",
        "https://1.1.1.1/hook",
        "https://8.8.8.8/hook",
    ],
)
async def test_resolve_public_address_allows_public_destinations(url, fake_dns_for_webhook_safety):
    ip, hostname, port = await resolve_public_address(url)
    assert ip
    assert hostname
    assert port == 443


async def test_resolve_public_address_rejects_unresolvable_host(fake_dns_for_webhook_safety):
    with pytest.raises(UnsafeWebhookURLError):
        await resolve_public_address("https://this-host-does-not-exist-anywhere.test/hook")


async def test_build_pinned_request_target_substitutes_ip_and_preserves_host_header(
    fake_dns_for_webhook_safety,
):
    pinned_url, headers, extensions = await build_pinned_request_target(
        "https://example.com/hook?x=1"
    )

    assert pinned_url == "https://93.184.216.34:443/hook?x=1"
    assert headers == {"Host": "example.com"}
    assert extensions == {"sni_hostname": "example.com"}


async def test_build_pinned_request_target_rejects_private_destination(
    fake_dns_for_webhook_safety,
):
    with pytest.raises(UnsafeWebhookURLError):
        await build_pinned_request_target("https://internal-service.test/hook")
