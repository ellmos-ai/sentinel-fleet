"""Outbound page reading with an SSRF guard, on the standard library alone.

Adapted from the author's `web-scraper` module (MIT), specifically its guard: resolve the target,
reject private, loopback, link-local, reserved, multicast and unspecified addresses, allow only
http(s), and re-check **every** redirect hop rather than only the first URL.

That last point is the one that matters here. This app runs on Cloud Run, where an unguarded
server-side fetch is a direct route to the instance metadata server on 169.254.169.254 and to
whatever else shares the network. "Fetch this URL" is an operator-supplied string, so the guard
treats it as hostile input: a public host that answers with a 302 to 127.0.0.1 is blocked at the
second hop, not followed into the container.

Left out of the adaptation on purpose: the module's `requests`, `beautifulsoup4`, `trafilatura`
and `selenium` paths (no new dependencies, no browser in this image) and its `allow_private`
escape hatch (there is no legitimate caller for it in a public deployment, and a flag that exists
gets set eventually).

The validated address is pinned at the connection layer while TLS still verifies the original
hostname. DNS is therefore consulted once per hop; a rebinding answer cannot replace the checked
public address between validation and connect.
"""

from __future__ import annotations

import ipaddress
import http.client
import re
import socket
import ssl
import threading
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = ("http", "https")
# A reader, not a downloader. Anything else - PDF, images, JSON APIs, archives - is refused with
# its type named, rather than fetched and handed to a text extractor that cannot read it.
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain")
MAX_RESPONSE_BYTES = 1_000_000
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 10
# What the caller gets back. A page can be far larger than anything worth putting in a prompt.
MAX_TEXT_CHARS = 20_000

USER_AGENT = "SentinelFleet/1.0 (governed agent fetch; GET only)"

# Cloud metadata endpoints are link-local and therefore already blocked by address class. They are
# named separately so the refusal says what was actually attempted, and so a hostname form that
# resolves elsewhere is still refused.
METADATA_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata",
    "instance-data",
})
LOCALHOST_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

_FETCH_CONTEXT = threading.local()


class WebReadError(RuntimeError):
    """The page could not be read."""


class BlockedTargetError(WebReadError):
    """The target was refused before any request went out."""


@dataclass
class RawResponse:
    """One HTTP hop's outcome, independent of the client that produced it."""

    url: str
    status: int
    content_type: str = ""
    charset: str = "utf-8"
    body: bytes = b""
    truncated: bool = False
    headers: Dict[str, str] = field(default_factory=dict)


def _address_block_reason(raw_ip: str) -> Optional[str]:
    """Name the reason an address is off limits, or None if it is a public target."""
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return f"'{raw_ip}' is not a parsable IP address"

    # ::ffff:127.0.0.1 is loopback wearing an IPv6 coat: the v6 object reports is_loopback False,
    # so the mapped v4 address has to be unwrapped before the checks mean anything.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped

    # Most specific class first. The ranges overlap - 169.254.0.0/16 and 0.0.0.0 both report
    # is_private True - and the refusal should say "link-local" or "unspecified" rather than
    # flattening every case to "private", because the reason is what the operator reads.
    for predicate, label in (
        (address.is_loopback, "loopback"),
        (address.is_link_local, "link-local"),
        (address.is_unspecified, "unspecified"),
        (address.is_multicast, "multicast"),
        (address.is_reserved, "reserved"),
        (address.is_private, "private"),
    ):
        if predicate:
            return f"{address} is a {label} address"
    return None


def guard_target(url: str) -> Tuple[str, List[str]]:
    """Refuse anything that is not a public http(s) target. Returns (hostname, resolved IPs)."""
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedTargetError(
            f"Only {' and '.join(ALLOWED_SCHEMES)} are allowed, not '{parsed.scheme or 'no scheme'}'"
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise BlockedTargetError("The URL carries no host")
    if host in LOCALHOST_NAMES:
        raise BlockedTargetError(f"'{host}' points at this container itself")
    if host in METADATA_HOSTS:
        raise BlockedTargetError(f"'{host}' is a cloud instance metadata endpoint")

    # A URL that already names an address needs no resolver: checking the literal is both cheaper
    # and stricter, since no name lookup sits between the check and what will be connected to.
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        literal = host.strip("[]")
        reason = _address_block_reason(literal)
        if reason:
            raise BlockedTargetError(f"Refused '{host}': {reason}")
        return host, [literal]

    try:
        resolved = sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror as exc:
        raise BlockedTargetError(f"Host '{host}' does not resolve ({exc.strerror or exc})") from exc

    if not resolved:
        raise BlockedTargetError(f"Host '{host}' resolved to no address")

    for candidate in resolved:
        reason = _address_block_reason(candidate)
        if reason:
            raise BlockedTargetError(f"Refused '{host}': {reason}")

    return host, resolved


def _same_address(left: str, right: str) -> bool:
    return ipaddress.ip_address(left) == ipaddress.ip_address(right)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, pinned_ip: str):
        super().__init__(host, port, timeout=TIMEOUT_SECONDS)
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        peer = self.sock.getpeername()[0]
        if not _same_address(peer, self.pinned_ip):
            self.sock.close()
            raise BlockedTargetError(
                f"Connected peer {peer} differs from validated address {self.pinned_ip}"
            )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, pinned_ip: str):
        super().__init__(host, port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        peer = raw.getpeername()[0]
        if not _same_address(peer, self.pinned_ip):
            raw.close()
            raise BlockedTargetError(
                f"Connected peer {peer} differs from validated address {self.pinned_ip}"
            )
        # The socket goes to the pinned IP; certificate validation and SNI still name the URL
        # host, preserving ordinary HTTPS authenticity.
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _fetch_from_ip(url: str, pinned_ip: str) -> Tuple[Optional[RawResponse], Optional[str]]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    connection_cls = _PinnedHTTPSConnection if parsed.scheme.lower() == "https" else _PinnedHTTPConnection
    connection = connection_cls(host, port, pinned_ip)
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    try:
        connection.request("GET", target, headers={"Host": host_header, "User-Agent": USER_AGENT})
        response = connection.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            if location:
                return None, location
        if response.status >= 400:
            raise WebReadError(f"HTTP {response.status}: {response.reason}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        return RawResponse(
            url=url,
            status=response.status,
            content_type=(response.headers.get_content_type() or "").lower(),
            charset=response.headers.get_content_charset() or "utf-8",
            body=body[:MAX_RESPONSE_BYTES],
            truncated=len(body) > MAX_RESPONSE_BYTES,
            headers={key: value for key, value in response.headers.items()},
        ), None
    finally:
        connection.close()


def _fetch_once(url: str) -> Tuple[Optional[RawResponse], Optional[str]]:
    """One HTTP hop pinned to an address already approved by ``guard_target``."""
    addresses = getattr(_FETCH_CONTEXT, "addresses", None)
    if not addresses:
        _, addresses = guard_target(url)
    last_error: Optional[Exception] = None
    for pinned_ip in addresses:
        try:
            response, location = _fetch_from_ip(url, pinned_ip)
            if response and response.content_type and response.content_type not in ALLOWED_CONTENT_TYPES:
                raise WebReadError(
                    f"'{response.content_type}' is not a readable page type; this reader accepts "
                    f"{' and '.join(ALLOWED_CONTENT_TYPES)}"
                )
            return response, location
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
            continue
        except (WebReadError, BlockedTargetError):
            raise
    if last_error is not None:
        raise WebReadError(f"{type(last_error).__name__}: {last_error}") from last_error
    raise WebReadError("No validated address was available for the connection")


class _PageText(HTMLParser):
    """Readable text out of HTML, on stdlib only.

    No DOM, no readability heuristics: chrome elements are dropped by tag name and the rest is
    flattened. That is less than a real extractor gets and more than enough to hand a page to a
    model - and it is the honest ceiling of what this deployment can claim.
    """

    DROPPED = frozenset({
        "script", "style", "noscript", "template", "svg", "canvas",
        "nav", "header", "footer", "aside", "form",
    })
    BLOCK = frozenset({
        "p", "div", "br", "li", "tr", "section", "article", "table",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
    })

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._parts: List[str] = []
        self._drop_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.DROPPED:
            self._drop_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.DROPPED:
            self._drop_depth = max(0, self._drop_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._drop_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        collapsed = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._parts))
        lines = [line.strip() for line in collapsed.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line is not None)).strip()


def extract_text(payload: str, content_type: str) -> Tuple[str, str]:
    """Return (text, title). Plain text is passed through; HTML is flattened."""
    if content_type == "text/plain":
        return payload.strip(), ""
    parser = _PageText()
    parser.feed(payload)
    parser.close()
    return parser.text(), parser.title.strip()


def read_page(url: str) -> Dict[str, object]:
    """Fetch and flatten one page. Blocking; call it off the event loop.

    Every hop is guarded, so a redirect cannot walk the fetch into the private network the first
    URL was checked against.
    """
    current = url
    redirects: List[str] = []

    for _ in range(MAX_REDIRECTS + 1):
        host, resolved = guard_target(current)
        _FETCH_CONTEXT.addresses = resolved
        try:
            response, location = _fetch_once(current)
        finally:
            _FETCH_CONTEXT.addresses = None
        if location is None:
            assert response is not None
            payload = response.body.decode(response.charset, errors="replace")
            text, title = extract_text(payload, response.content_type)
            return {
                "requested_url": url,
                "url": response.url,
                "host": host,
                "resolved_addresses": resolved,
                "status": response.status,
                "content_type": response.content_type,
                "title": title,
                "text": text[:MAX_TEXT_CHARS],
                "characters": len(text),
                "text_truncated": len(text) > MAX_TEXT_CHARS,
                "body_truncated": response.truncated,
                "redirects": redirects,
            }
        current = urljoin(current, location)
        redirects.append(current)

    raise WebReadError(f"More than {MAX_REDIRECTS} redirects, giving up at {current}")
