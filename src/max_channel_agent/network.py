"""Bounded HTTP collection with DNS pinning, TLS SNI and per-redirect checks."""

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .config import AgentError


def validate_url(url, resolve=True, resolver=None):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        if (
            parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                raise ValueError
            addresses = [str(address)]
        except ValueError:
            if resemblances_ip(host):
                raise ValueError from None
            addresses = []
        if resolve and not addresses:
            lookup = resolver or socket.getaddrinfo
            addresses = list(
                {
                    r[4][0]
                    for r in lookup(
                        host,
                        parsed.port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM,
                    )
                }
            )
        if resolve and (
            not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses)
        ):
            raise ValueError
        return host, addresses
    except (ValueError, OSError) as exc:
        raise AgentError("SOURCE_URL_FORBIDDEN") from exc


def resemblances_ip(host):
    # Reject private literal addresses, unusual numeric IPv4 forms and IPv6 after parse failure.
    return ":" in host or host.replace(".", "").isdigit() or host.startswith("0x")


def canonical_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


class SafeHTTP:
    def __init__(self, max_bytes=5242880, redirects=3, transport=None, resolver=None):
        self.max_bytes, self.redirects, self.resolver = max_bytes, redirects, resolver
        self.client = httpx.Client(
            timeout=30, follow_redirects=False, trust_env=False, transport=transport
        )

    def get(self, url, headers=None):
        original_host = None
        headers = dict(headers or {})
        for _ in range(self.redirects + 1):
            host, addresses = validate_url(url, resolver=self.resolver)
            if original_host and host != original_host:
                headers = {
                    k: v for k, v in headers.items() if k.lower() not in {"authorization", "cookie"}
                }
            original_host = host
            original = httpx.URL(url)
            # Connect to the already verified address rather than resolving DNS a second time.
            pinned = original.copy_with(host=addresses[0])
            request_headers = {**headers, "Host": original.netloc.decode()}
            try:
                with self.client.stream(
                    "GET", pinned, headers=request_headers, extensions={"sni_hostname": host}
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise AgentError("SOURCE_BAD_REDIRECT")
                        url = urljoin(url, location)
                        continue
                    if response.status_code in {401, 403, 429}:
                        raise AgentError(f"SOURCE_HTTP_{response.status_code}")
                    if response.status_code == 304:
                        return 304, b"", dict(response.headers), url
                    if response.status_code != 200:
                        raise AgentError("SOURCE_HTTP_ERROR")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise AgentError("SOURCE_TOO_LARGE")
                        chunks.append(chunk)
                    return 200, b"".join(chunks), dict(response.headers), url
            except httpx.HTTPError as exc:
                raise AgentError("SOURCE_TRANSPORT_ERROR") from exc
        raise AgentError("SOURCE_REDIRECT_LIMIT")

    def close(self):
        self.client.close()
