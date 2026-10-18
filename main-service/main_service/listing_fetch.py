"""Fetch supplier evidence without allowing candidate URLs to access internal services."""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from .candidates import listing_url


class EvidenceError(ValueError):
    pass


@dataclass
class ListingPage:
    url: str
    body: bytes


class ListingFetcher:
    def __init__(self, resolver=None, transport=None):
        self.resolver = resolver or self.resolve
        self.transport = transport

    @staticmethod
    async def resolve(host):
        addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return list(dict.fromkeys(row[4][0] for row in addresses))

    async def fetch(self, url: str) -> ListingPage:
        try:
            async with asyncio.timeout(20):
                return await self._fetch(url)
        except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
            raise EvidenceError(str(exc)) from exc

    async def _fetch(self, url: str) -> ListingPage:
        for _ in range(4):
            listing_url(url)
            host = urlsplit(url).hostname
            addresses = await self.resolver(host)
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise EvidenceError('listing host resolves to a non-public address')
            # Pin the actual connection to a checked IP while retaining the original TLS identity.
            target = httpx.URL(url).copy_with(host=addresses[0], fragment='')
            async with httpx.AsyncClient(transport=self.transport, trust_env=False, timeout=10,
                                         follow_redirects=False) as client:
                async with client.stream('GET', target, headers={
                    'Host': httpx.URL(url).netloc.decode(), 'Accept': 'text/html,application/ld+json,application/json',
                    'User-Agent': 'papr-listing-verifier/1.0', 'Accept-Encoding': 'identity',
                }, extensions={'sni_hostname': host}) as response:
                    if response.is_redirect:
                        if not response.headers.get('location'):
                            raise EvidenceError('listing redirect has no destination')
                        url = urljoin(url, response.headers['location'])
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get('content-type', '').split(';')[0].lower()
                    if content_type not in ('text/html', 'application/xhtml+xml', 'application/ld+json', 'application/json'):
                        raise EvidenceError('listing does not provide HTML or JSON evidence')
                    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise EvidenceError('compressed listing response is unsupported')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000:
                            raise EvidenceError('listing exceeds the evidence size limit')
                    return ListingPage(url, bytes(body))
        raise EvidenceError('too many listing redirects')
