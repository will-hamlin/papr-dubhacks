"""Explicit local demo: real orchestration/checks, fictional catalog and source pages."""
import json
import os

from .app import create_app as create_service_app
from .listing_fetch import EvidenceError, ListingPage
from .verification import ListingVerifier


def product(name, sku, category, price, properties):
    return {'@context': 'https://schema.org', '@type': 'Product', 'name': name, 'sku': sku,
            'category': category, 'itemCondition': 'https://schema.org/NewCondition',
            'additionalProperty': properties,
            'offers': {'@type': 'Offer', 'price': price, 'priceCurrency': 'USD'}}


CATALOG = {
    'charger-65': product('USB-C charger', 'DEMO-CH65', 'computer_accessories', '25.00',
                         [{'name': 'power', 'value': 65, 'unitText': 'W'},
                          {'name': 'connector', 'value': 'USB-C'}]),
    'charger-30': product('USB-C charger', 'DEMO-CH30', 'computer_accessories', '18.00',
                         [{'name': 'power', 'value': 30, 'unitText': 'W'},
                          {'name': 'connector', 'value': 'USB-C'}]),
    'laptop-32': product('Laptop', 'DEMO-L32', 'electronics', '799.00',
                        [{'name': 'ram', 'value': 32, 'unitText': 'GB'}]),
    'laptop-16': product('Laptop', 'DEMO-L16', 'electronics', '599.00',
                        [{'name': 'ram', 'value': 16, 'unitText': 'GB'}]),
    'stapler': product('Stapler', 'DEMO-ST', 'office_supplies', '20.00', []),
}
ORIGIN = 'https://catalog.papr.example/'


def candidate(slug):
    entry = CATALOG[slug]
    # Deliberately overclaimed weak variants demonstrate independent contradiction checks.
    claim = {'field': 'power', 'value': 65, 'unit': 'W'} if slug.startswith('charger') else \
            {'field': 'ram', 'value': 32, 'unit': 'GB'} if slug.startswith('laptop') else \
            {'field': 'price_cents', 'value': 2000}
    return {'candidate_id': slug, 'url': ORIGIN + slug, 'sku': entry['sku'], 'claims': [claim]}


class DemoPages:
    async def fetch(self, url):
        pages = {ORIGIN + slug: entry for slug, entry in CATALOG.items()}
        if url not in pages:
            raise EvidenceError('Demo mode only checks the documented fictional catalog URLs')
        return ListingPage(url, json.dumps(pages[url], sort_keys=True).encode())


class DemoVerifier(ListingVerifier):
    def __init__(self):
        super().__init__(DemoPages(), {'catalog.papr.example': 'sup_01'})

    async def verify(self, candidate, specs, limits):
        report = await super().verify(candidate, specs, limits)
        report.update(simulated=True, simulation_note='Fictional supplier evidence; no web search or purchase')
        if 'evidence' in report:
            page = await self.fetcher.fetch(candidate.url)
            report['evidence'].update(basis='demo_fixture', snapshot_utf8=page.body.decode(),
                                      fixture_version='papr-demo-catalog-v1')
        return report


class DemoEngine:
    name = 'demo_fixture'

    async def search(self, payload):
        item = payload['specs']['item'].casefold()
        slugs = ['charger-65', 'charger-30', 'stapler'] if 'charger' in item else \
                ['laptop-32', 'laptop-16', 'stapler'] if 'laptop' in item else []
        return {'status': 'completed', 'demo': True, 'purchase_authorized': False,
                'message': 'Fictional catalog; real listing checks and Z3 proofs. No live search or purchase.',
                'candidates': [candidate(slug) for slug in slugs]}


def create_app(settings=None, parser=None):
    if os.environ.get('PAPR_ENV', 'development') != 'development' or os.environ.get('PAPR_DEMO_MODE') != '1':
        raise RuntimeError('Demo factory requires PAPR_ENV=development and PAPR_DEMO_MODE=1')
    app = create_service_app(settings, parser, DemoEngine(), DemoVerifier())
    app.title = 'PAPR local demo — simulated supplier evidence'

    @app.get('/demo/catalog')
    def catalog():
        return {'demo': True, 'supplier_id': 'sup_01', 'candidates': [candidate(slug) for slug in CATALOG]}

    return app
