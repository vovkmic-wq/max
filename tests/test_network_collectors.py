import json
import socket

import httpx
import pytest

from max_channel_agent.collectors import clean_html, collect_web
from max_channel_agent.config import AgentError
from max_channel_agent.network import SafeHTTP, canonical_url, validate_url


def resolver(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", port))]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://localhost",
        "http://10.0.0.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "file:///x",
        "http://2130706433",
        "http://0x7f000001",
        "http://user:secret@example.org",
        "http://example.org:8080",
        "https://x.local",
    ],
)
def test_ssrf_literals(url):
    with pytest.raises(AgentError):
        validate_url(url, resolve=False)


def test_dns_rebinding_blocked():
    def bad(host, port, **kwargs):
        return [(2, 1, 0, "", ("127.0.0.1", port))]

    with pytest.raises(AgentError):
        validate_url("https://public.example", resolver=bad)


def test_pinned_address_and_sni():
    def handle(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.org"
        assert request.extensions["sni_hostname"] == "example.org"
        return httpx.Response(200, content=b"ok")

    with_http = SafeHTTP(transport=httpx.MockTransport(handle), resolver=resolver)
    assert with_http.get("https://example.org")[1] == b"ok"
    with_http.close()


def test_redirect_private_blocked():
    client = SafeHTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1"})
        ),
        resolver=resolver,
    )
    with pytest.raises(AgentError, match="SOURCE_URL_FORBIDDEN"):
        client.get("https://example.org")
    client.close()


def test_large_response_blocked():
    client = SafeHTTP(
        max_bytes=3,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"four")),
        resolver=resolver,
    )
    with pytest.raises(AgentError, match="SOURCE_TOO_LARGE"):
        client.get("https://example.org")
    client.close()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_source_errors_stop(status):
    calls = []

    def handle(r):
        calls.append(r)
        return httpx.Response(status)

    client = SafeHTTP(transport=httpx.MockTransport(handle), resolver=resolver)
    with pytest.raises(AgentError):
        client.get("https://example.org")
    assert len(calls) == 1
    client.close()


def test_canonical_preserves_meaningful_query():
    assert (
        canonical_url("https://EXAMPLE.org/article?id=2#part") == "https://example.org/article?id=2"
    )


def test_rss_and_304(service):
    rss = b'<rss version="2.0"><channel><title>Video</title><item><guid>x</guid><title>AI video</title><link>https://example.org/a</link><description>Short video</description><pubDate>Tue, 06 Oct 2026 00:00:00 GMT</pubDate></item></channel></rss>'

    class HTTP:
        def get(self, *args):
            return 200, rss, {"etag": "v1"}, "https://example.org"

    source = service.settings.sources["sources"][0]
    items, cursor = collect_web(source, {}, HTTP(), service.settings.root)
    assert len(items) == 1 and items[0].external_id == "x" and cursor["etag"] == "v1"

    class NotModified:
        def get(self, *args):
            return 304, b"", {}, "https://example.org"

    assert collect_web(source, cursor, NotModified(), service.settings.root) == ([], cursor)


def test_html_profile(project, service):
    directory = project / "config/extraction"
    directory.mkdir()
    (directory / "article.json").write_text(
        json.dumps({"body_selector": "article", "title_selector": "h1"})
    )
    source = {
        **service.settings.sources["sources"][0],
        "type": "html",
        "extraction_profile": "article",
    }

    class HTTP:
        def get(self, *args):
            return (
                200,
                b"<h1>Video</h1><article>Text<script>evil()</script></article>",
                {},
                "https://example.org",
            )

    items, _ = collect_web(source, {}, HTTP(), project)
    assert items[0].text == "Text"
    assert clean_html("<p>a</p><script>secret</script>") == "a"
