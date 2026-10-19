"""Shared listing-evidence checks for managed search and personal-agent submissions.

The evidence is what the supplier publishes now, not a guarantee of physical product truth.
No candidate rankings, optimality assertions, or purchase authorization are produced here.
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .listing_fetch import EvidenceError, ListingFetcher
from .proof import UNITS

UNIT_CODES = {'WTT': 'W', 'KGM': 'kg', 'GRM': 'g', 'MMT': 'mm', 'CMT': 'cm', 'MTR': 'm', 'INH': 'in'}
CONDITIONS = {'NewCondition': 'new', 'UsedCondition': 'used', 'RefurbishedCondition': 'refurbished'}

# A deliberately small demo vocabulary. Unknown types do not establish product suitability.
PRODUCT_TYPES = {
    'laptop': r'laptops?|notebook computers?',
    'charger': r'chargers?|power adapters?|power suppl(?:y|ies)',
    'monitor': r'monitors?|displays?',
    'keyboard': r'keyboards?', 'mouse': r'mouse|mice',
    'dock': r'docks?|docking stations?', 'hub': r'usb hubs?', 'cable': r'cables?',
    'stapler': r'staplers?', 'paper': r'paper', 'pen': r'pens?', 'notebook': r'notebooks?',
    'toner': r'toners?', 'ink': r'printer ink',
    'chair': r'chairs?', 'desk': r'desks?', 'cabinet': r'filing cabinets?',
    'drill': r'drills?', 'saw': r'saws?', 'wrench': r'wrenches?', 'hammer': r'hammers?',
    'screwdriver': r'screwdrivers?', 'multimeter': r'multimeters?',
    'hard_hat': r'hard hats?', 'safety_glasses': r'safety glasses', 'gloves': r'gloves?',
    'vest': r'vests?', 'respirator': r'respirators?',
    'case': r'cases?|sleeves?|pouches?', 'stand': r'stands?', 'mount': r'mounts?|brackets?|arms?',
    'battery': r'batter(?:y|ies)', 'bag': r'bags?|backpacks?', 'screen': r'screens?',
    'cover': r'covers?|protectors?', 'replacement_part': r'replacement parts?',
}
ACCESSORY_TYPES = {'case', 'stand', 'mount', 'cover', 'replacement_part', 'battery', 'bag', 'screen'}


def _product_type(text):
    # Compatibility targets in a title are not the product being sold.
    title = re.split(r'\b(?:for|compatible with)\b', text.casefold(), maxsplit=1)[0]
    kinds = {kind for kind, pattern in PRODUCT_TYPES.items() if re.search(r'\b(?:' + pattern + r')\b', title)}
    if kinds == {'laptop', 'notebook'}:
        return 'laptop'
    accessories = kinds & ACCESSORY_TYPES
    if len(accessories) == 1:
        return next(iter(accessories))
    if kinds == {'laptop', 'charger'}:
        return 'charger'
    return next(iter(kinds)) if len(kinds) == 1 else None


def product_identity(specs, facts):
    expected = specs.get('item', '')
    published = facts.get('name')
    observed = published.get('value') if published else None
    output = {'field': 'product_identity', 'expected': expected, 'observed': observed}
    if not isinstance(expected, str) or not isinstance(observed, str):
        return {**output, 'status': 'unverified', 'reason': 'missing published product identity'}
    wanted, actual = _product_type(expected), _product_type(observed)
    if wanted is None or actual is None:
        return {**output, 'status': 'unverified', 'reason': 'product type is outside the demo vocabulary or ambiguous'}
    if wanted != actual:
        return {**output, 'status': 'contradicted', 'reason': 'published product type differs from the requested item'}
    # A shared noun alone does not establish requested model/brand/other descriptive qualifiers.
    remainder = re.sub(r'\b(?:' + PRODUCT_TYPES[wanted] + r')\b', ' ', expected.casefold())
    qualifiers = set(re.findall(r'[a-z0-9]+', remainder)) - {'a', 'an', 'the'}
    if not qualifiers.issubset(set(re.findall(r'[a-z0-9]+', observed.casefold()))):
        return {**output, 'status': 'unverified', 'reason': 'requested identity qualifiers are not established by the listing name'}
    return {**output, 'status': 'supported', 'basis': 'published_product_type_and_requested_identity_words'}


class JsonLD(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type', '').lower() == 'application/ld+json':
            self.active, self.parts = True, []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.documents.append(''.join(self.parts))
            self.active = False


def _products(value, depth=0):
    if depth > 30:
        raise EvidenceError('listing data is nested too deeply')
    if isinstance(value, list):
        for item in value:
            yield from _products(item, depth + 1)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        types = [types] if isinstance(types, str) else types
        if not isinstance(types, list):
            types = []
        if 'Product' in types or 'https://schema.org/Product' in types:
            yield value
        for key in ('@graph', 'hasVariant', 'mainEntity'):
            if key in value:
                yield from _products(value[key], depth + 1)


def extract_facts(body: bytes, sku: str | None) -> dict:
    text = body.decode('utf-8', errors='replace')
    parser = JsonLD()
    parser.feed(text)
    documents = parser.documents or [text]
    products = []
    for document in documents:
        try:
            products.extend(_products(json.loads(document, parse_float=str)))
        except (json.JSONDecodeError, RecursionError) as exc:
            raise EvidenceError('invalid structured listing evidence') from exc
    if sku is not None:
        products = [p for p in products if p.get('sku') == sku]
    if len(products) != 1:
        raise EvidenceError('could not bind the listing to one unambiguous product/variant')
    product = products[0]
    facts = {}

    def put(field, value, unit=None):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return
        entry = {'value': value, 'unit': unit}
        if field in facts and facts[field] != entry:
            facts[field] = None  # Conflicting source values cannot establish a fact.
        else:
            facts[field] = entry

    for field in ('name', 'sku', 'category', 'color', 'material', 'model'):
        put(field, product.get(field))
    brand = product.get('brand')
    put('brand', brand.get('name') if isinstance(brand, dict) else brand)
    for field in ('weight', 'width', 'height', 'depth'):
        value = product.get(field)
        if isinstance(value, dict):
            put(field, value.get('value'), value.get('unitText') or UNIT_CODES.get(value.get('unitCode')))
    properties = product.get('additionalProperty', [])
    properties = [properties] if isinstance(properties, dict) else properties
    if isinstance(properties, list):
        for prop in properties:
            if not isinstance(prop, dict) or not isinstance(prop.get('name'), str):
                continue
            field = re.sub(r'[^a-z0-9]+', '_', prop['name'].lower()).strip('_')
            # Pricing, identity, and seller information must come from their dedicated schema fields.
            if field in ('name', 'sku', 'category', 'price_cents', 'currency', 'supplier_id', 'condition'):
                continue
            put(field, prop.get('value'), prop.get('unitText') or UNIT_CODES.get(prop.get('unitCode')))
    condition = product.get('itemCondition')
    if isinstance(condition, str):
        put('condition', CONDITIONS.get(condition.rsplit('/', 1)[-1]))
    offers = product.get('offers', [])
    offers = [offers] if isinstance(offers, dict) else offers
    if isinstance(offers, list) and len(offers) == 1 and isinstance(offers[0], dict):
        offer = offers[0]
        if offer.get('@type') in ('Offer', 'https://schema.org/Offer'):
            try:
                if 'priceValidUntil' in offer and date.fromisoformat(offer['priceValidUntil']) < datetime.now(timezone.utc).date():
                    raise ValueError('published price has expired')
                price = Decimal(str(offer['price'])) * 100
                if price.is_finite() and 0 <= price <= 10**12 and price == price.to_integral_value():
                    put('price_cents', int(price))
                    put('currency', offer.get('priceCurrency'))
            except (KeyError, InvalidOperation, ValueError, TypeError):
                pass
            put('availability', offer.get('availability'))
            condition = offer.get('itemCondition')
            if isinstance(condition, str):
                put('condition', CONDITIONS.get(condition.rsplit('/', 1)[-1]))
    return facts


def normalized(value, unit):
    if unit is None:
        return value, None
    if unit not in UNITS and unit not in ('mV',):
        raise EvidenceError('unsupported or missing source unit')
    base, factor = UNITS.get(unit, ('mV', Decimal(1)))
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > 10**18:
            raise InvalidOperation
    except InvalidOperation as exc:
        raise EvidenceError('non-numeric source measurement') from exc
    return number * factor, base


def check(field, expected, unit, facts, op='eq'):
    fact = facts.get(field)
    output = {'field': field, 'op': op, 'expected': expected, 'unit': unit, 'observed': fact}
    if fact is None:
        return {**output, 'status': 'unverified', 'reason': 'missing or conflicting published evidence'}
    try:
        left, left_unit = normalized(fact['value'], fact['unit'])
        right, right_unit = normalized(expected, unit)
        if left_unit != right_unit:
            raise EvidenceError('source and claim units do not match')
        if isinstance(left, str) and isinstance(right, str):
            left, right = left.strip().casefold(), right.strip().casefold()
        if type(left) is not type(right) and not isinstance(left, Decimal):
            raise EvidenceError('source and claim value types do not match')
        passed = {'eq': lambda: left == right, 'ne': lambda: left != right,
                  'ge': lambda: left >= right, 'le': lambda: left <= right}[op]()
        return {**output, 'status': 'supported' if passed else 'contradicted'}
    except (EvidenceError, TypeError, KeyError) as exc:
        return {**output, 'status': 'unverified', 'reason': str(exc)}


def aggregate(checks):
    if any(c['status'] == 'contradicted' for c in checks):
        return 'contradicted'
    if not checks or any(c['status'] != 'supported' for c in checks):
        return 'unverified'
    return 'supported'


class ListingVerifier:
    def __init__(self, fetcher=None, supplier_hosts=None):
        self.fetcher = fetcher or ListingFetcher()
        # Configured by the service operator, never taken from candidate claims.
        self.supplier_hosts = supplier_hosts or {}

    async def verify(self, candidate, specs, limits):
        result = {'candidate_id': candidate.candidate_id, 'url': candidate.url, 'sku': candidate.sku,
                  'claims': [c.model_dump() for c in candidate.claims], 'claims_status': 'unverified',
                  'requirements_status': 'unverified', 'purchase_authorized': False}
        try:
            page = await self.fetcher.fetch(candidate.url)
            result['evidence'] = {'url': page.url, 'sha256': hashlib.sha256(page.body).hexdigest(),
                                  'retrieved_at': datetime.now(timezone.utc).isoformat(),
                                  'basis': 'supplier_published_structured_data'}
            facts = extract_facts(page.body, candidate.sku)
        except EvidenceError as exc:
            result['reason'] = str(exc)
            return result
        claims = [check(c.field, c.value, c.unit, facts) for c in candidate.claims]
        requirements = [check(c['field'], c['value'], c['unit'], facts, c['op'])
                        for c in specs['constraints'] if c['required']]
        requirements.append(product_identity(specs, facts))
        if specs.get('unsupported_requirements'):
            requirements.append({'field': 'unsupported_requirements', 'status': 'unverified',
                                 'expected': specs['unsupported_requirements'],
                                 'reason': 'some requested requirements could not be compiled'})
        if specs['condition'] != 'unspecified':
            requirements.append(check('condition', specs['condition'], None, facts))
        requirements.append(check('currency', limits['currency'], None, facts))
        supplier = self.supplier_hosts.get(urlsplit(page.url).hostname)
        supplier_ok = supplier in limits['approved_suppliers'] if supplier else None
        requirements.append({'field': 'approved_supplier', 'observed': supplier,
                             'status': 'supported' if supplier_ok else 'contradicted' if supplier else 'unverified'})
        price = facts.get('price_cents')
        freight = limits['freight_cents_by_supplier'].get(supplier)
        total = None
        if price and type(price['value']) is int and type(freight) is int and freight >= 0:
            subtotal = price['value'] * specs['quantity']
            tax = int((Decimal(subtotal) * limits['tax_rate_bp'] / 10000).to_integral_value(rounding=ROUND_HALF_UP))
            total = subtotal + tax + freight
        requirements.append({'field': 'max_total_cents', 'observed': total, 'expected': limits['max_total_cents'],
                             'status': 'unverified' if total is None else
                                       'supported' if total <= limits['max_total_cents'] else 'contradicted',
                             'basis': 'configured_tax_and_freight'})
        category = facts.get('category')
        known_categories = {'electronics', 'computer_accessories', 'office_supplies', 'tools', 'safety_equipment',
                            'furniture', 'software', 'cleaning_supplies', 'weapons', 'medicine',
                            'age_restricted', 'gift_cards'}
        category_value = category['value'] if category else None
        requirements.append({'field': 'category', 'observed': category_value,
                             'status': 'unverified' if category_value not in known_categories else
                                       'contradicted' if category_value in limits['blocked_categories'] or
                                       (specs.get('category') in known_categories and category_value != specs['category']) else 'supported'})
        result.update(facts=facts, claim_checks=claims, requirement_checks=requirements,
                      claims_status=aggregate(claims), requirements_status=aggregate(requirements))
        from .formal import prove_listing
        result['formal_proof'] = prove_listing(result, specs, limits)
        return result
