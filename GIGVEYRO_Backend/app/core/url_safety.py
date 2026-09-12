"""SSRF-safe HTTP destination validation for merchant-supplied webhook URLs.

Merchants configure an arbitrary URL that a trusted backend worker later
POSTs to. Without validation this is a direct request-forgery primitive
against the platform's own internal network (Docker service names, the
Postgres/Redis containers, cloud metadata endpoints, etc).

Validation happens at two points:
  1. Structural check (scheme/hostname present) - cheap, runs inside the
     Pydantic schema validator, no network I/O.
  2. DNS resolution + address-family inspection - runs both when a webhook
     is created/updated AND again immediately before every delivery
     attempt. Checking only at creation time is not enough: an attacker
     fully controls their own DNS record and can point it at a private
     address after the fact (DNS rebinding). Re-resolving right before
     connecting narrows, but by itself does not close, that window - the
     actual TCP connection is therefore pinned to the exact address that
     was just validated (see build_pinned_request_target), rather than
     letting the HTTP client re-resolve DNS a second time at connect time.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit


class UnsafeWebhookURLError(ValueError):
    """Raised when a URL fails SSRF-safety validation."""


def validate_webhook_url_syntax(url: str) -> str:
    """Cheap, synchronous, no network I/O - safe to call from a Pydantic
    field validator. Does not resolve DNS; see resolve_public_address."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UnsafeWebhookURLError("webhook url must use https://")
    if not parts.hostname:
        raise UnsafeWebhookURLError("webhook url must include a hostname")
    return url


def _is_public_ip(raw_ip: str) -> bool:
    ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _getaddrinfo(hostname: str, port: int) -> list[tuple]:
    """Isolated so tests can monkeypatch DNS resolution instead of making
    real network calls - the SSRF-safety logic itself still runs for real
    against whatever addresses the patched resolver returns."""
    return await asyncio.to_thread(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)


async def resolve_public_address(url: str) -> tuple[str, str, int]:
    """Resolves the URL's hostname and confirms every address it resolves
    to is public/routable - rejecting the whole URL if even one resolved
    address is private/loopback/link-local/etc (a hostname can round-robin
    across multiple addresses; if any of them is internal, treat the whole
    destination as unsafe rather than gambling on which one gets used).

    Returns (validated_ip, hostname, port) for the caller to pin the actual
    connection to - the exact address just checked, not a fresh lookup.
    """
    validate_webhook_url_syntax(url)
    parts = urlsplit(url)
    hostname = parts.hostname
    assert hostname is not None  # enforced by validate_webhook_url_syntax
    port = parts.port or 443

    try:
        infos = await _getaddrinfo(hostname, port)
    except socket.gaierror as exc:
        raise UnsafeWebhookURLError(f"could not resolve webhook host: {exc}") from exc
    if not infos:
        raise UnsafeWebhookURLError("webhook host did not resolve to any address")

    resolved_ips = sorted({info[4][0] for info in infos})
    for raw_ip in resolved_ips:
        if not _is_public_ip(raw_ip):
            raise UnsafeWebhookURLError(
                f"webhook host resolves to a non-public address ({raw_ip})"
            )

    return resolved_ips[0], hostname, port


async def build_pinned_request_target(
    url: str,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Validates url and returns a (pinned_url, extra_headers, extensions)
    tuple such that issuing the HTTP request against pinned_url with those
    headers/extensions connects to the exact validated IP while still
    presenting the correct Host header and TLS SNI/certificate hostname -
    an httpx client re-resolving DNS on the substituted hostname would
    reopen the DNS-rebinding window this function exists to close.
    """
    ip, hostname, port = await resolve_public_address(url)
    parts = urlsplit(url)
    netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
    pinned_url = SplitResult(parts.scheme, netloc, parts.path, parts.query, parts.fragment).geturl()
    return pinned_url, {"Host": hostname}, {"sni_hostname": hostname}
