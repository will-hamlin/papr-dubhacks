"""Exact unit conversion to integer base units (invariant 13).

Every factor is a fractions.Fraction; numbers are parsed from strings, never floats.
A value whose base-unit result is not an exact integer is unreadable, never rounded.
Different size systems (US men's, US women's, EU, UK) are distinct dimensions, so
they can never be converted into each other.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# unit -> (dimension, base unit, factor to base)
_UNITS: dict[str, tuple[str, str, Fraction]] = {
    # length, base micrometres
    "um": ("[length]", "um", Fraction(1)),
    "mm": ("[length]", "um", Fraction(1000)),
    "cm": ("[length]", "um", Fraction(10_000)),
    "m": ("[length]", "um", Fraction(1_000_000)),
    "in": ("[length]", "um", Fraction(25_400)),
    "ft": ("[length]", "um", Fraction(304_800)),
    # mass, base picograms: avoirdupois oz (28.349523125 g) is exact to 0.001 oz, lb to 0.000001 lb
    "pg": ("[mass]", "pg", Fraction(1)),
    "ng": ("[mass]", "pg", Fraction(1000)),
    "mg": ("[mass]", "pg", Fraction(1_000_000_000)),
    "g": ("[mass]", "pg", Fraction(1_000_000_000_000)),
    "kg": ("[mass]", "pg", Fraction(1_000_000_000_000_000)),
    "oz": ("[mass]", "pg", Fraction(28_349_523_125_000)),
    "lb": ("[mass]", "pg", Fraction(453_592_370_000_000)),
    # power, base milliwatts
    "mW": ("[power]", "mW", Fraction(1)),
    "W": ("[power]", "mW", Fraction(1000)),
    "kW": ("[power]", "mW", Fraction(1_000_000)),
    # electric potential, base millivolts
    "mV": ("[voltage]", "mV", Fraction(1)),
    "V": ("[voltage]", "mV", Fraction(1000)),
    # current, base milliamps
    "mA": ("[current]", "mA", Fraction(1)),
    "A": ("[current]", "mA", Fraction(1000)),
    # money, base cents (USD only; other currencies are unreadable)
    "cents": ("[money]", "cents", Fraction(1)),
    "USD": ("[money]", "cents", Fraction(100)),
    # durations and dates, base days
    "days": ("[time]", "days", Fraction(1)),
    "weeks": ("[time]", "days", Fraction(7)),
    "hours": ("[time]", "days", Fraction(1, 24)),
    # sound level, base decidecibels
    "dB": ("[sound]", "ddB", Fraction(10)),
    # star ratings, base tenths of a star
    "stars": ("[rating]", "tenth_stars", Fraction(10)),
    # dimensionless counts
    "count": ("[count]", "count", Fraction(1)),
    # shoe sizes: each system is its own dimension; base is tenths of a size
    "US_M": ("[shoe_size_us_men]", "us_m_tenths", Fraction(10)),
    "US_W": ("[shoe_size_us_women]", "us_w_tenths", Fraction(10)),
    "EU": ("[shoe_size_eu]", "eu_tenths", Fraction(10)),
    "UK": ("[shoe_size_uk]", "uk_tenths", Fraction(10)),
    # data capacity, base megabytes (decimal)
    "MB": ("[data]", "MB", Fraction(1)),
    "GB": ("[data]", "MB", Fraction(1000)),
    "TB": ("[data]", "MB", Fraction(1_000_000)),
    # battery capacity
    "mAh": ("[charge]", "mAh", Fraction(1)),
    "Wh": ("[energy]", "mWh", Fraction(1000)),
}

_ALIASES: dict[str, str] = {
    "µm": "um", "micrometer": "um", "micrometers": "um",
    "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "centimeter": "cm", "centimeters": "cm", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    '"': "in", "”": "in", "inch": "in", "inches": "in", "in.": "in",
    "'": "ft", "foot": "ft", "feet": "ft", "ft.": "ft",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg",
    "ounce": "oz", "ounces": "oz", "oz.": "oz", "pound": "lb", "pounds": "lb", "lbs": "lb", "lb.": "lb",
    "milliwatt": "mW", "mw": "mW", "w": "W", "watt": "W", "watts": "W", "kw": "kW",
    "v": "V", "volt": "V", "volts": "V", "mv": "mV",
    "a": "A", "amp": "A", "amps": "A", "ma": "mA",
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "us$": "USD",
    "cent": "cents", "¢": "cents",
    "day": "days", "d": "days", "week": "weeks", "wk": "weeks", "hour": "hours", "hr": "hours", "hrs": "hours", "h": "hours",
    "db": "dB", "dba": "dB", "db(a)": "dB",
    "pcs": "count", "pieces": "count", "piece": "count", "units": "count", "settings": "count", "ct": "count",
    "us": "US_M", "us m": "US_M", "us men": "US_M", "us men's": "US_M", "us_m": "US_M", "us mens": "US_M",
    "us w": "US_W", "us women": "US_W", "us women's": "US_W", "us_w": "US_W", "us womens": "US_W",
    "eu": "EU", "uk": "UK",
    "star": "stars", "stars": "stars",
    "gb": "GB", "mb": "MB", "tb": "TB", "mah": "mAh", "wh": "Wh",
}


@dataclass(frozen=True)
class Conversion:
    value: int | None          # None = unreadable
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = unit.strip()
    if u in _UNITS:
        return u
    low = u.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    if u in _ALIASES:
        return _ALIASES[u]
    for k in _UNITS:
        if k.lower() == low:
            return k
    return None


def unit_info(unit: str) -> tuple[str, str, Fraction] | None:
    n = normalize_unit(unit)
    return _UNITS.get(n) if n else None


def dimension_of(unit: str) -> str | None:
    info = unit_info(unit)
    return info[0] if info else None


def base_unit_for(dimension: str) -> str | None:
    for dim, base, _ in _UNITS.values():
        if dim == dimension:
            return base
    return None


_NUM_RE = re.compile(r"^[+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$|^[+]?\.\d+$|^\d+/\d+$|^\d+ \d+/\d+$")


def parse_number(text: str | int) -> Fraction | None:
    """Exact parse of a decimal, thousands-separated, or fraction string. No floats."""
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return Fraction(text)
    if not isinstance(text, str):
        return None          # floats and other types are rejected outright
    t = text.strip()
    if t.endswith("½") and t[:-1].isdigit():
        t = t[:-1] + ".5"
    if not _NUM_RE.match(t):
        return None
    if " " in t:             # mixed number "1 1/2"
        whole, frac = t.split(" ")
        return Fraction(int(whole)) + Fraction(frac)
    return Fraction(t.replace(",", ""))


def to_base(value: str | int | Fraction, unit: str, expected_dimension: str | None = None) -> Conversion:
    n = normalize_unit(unit)
    if n is None:
        return Conversion(None, f"unknown unit {unit!r}")
    dim, _, factor = _UNITS[n]
    if expected_dimension and dim != expected_dimension:
        return Conversion(None, f"dimension mismatch: {unit} is {dim}, field needs {expected_dimension}")
    q = value if isinstance(value, Fraction) else parse_number(value)
    if q is None:
        return Conversion(None, f"unreadable number {value!r}")
    if q < 0:
        return Conversion(None, "negative quantity")
    b = q * factor
    if b.denominator != 1:
        return Conversion(None, f"{value} {unit} is not an exact integer in base units ({b})")
    return Conversion(int(b))


def from_base(value: int, unit: str) -> Fraction:
    n = normalize_unit(unit)
    if n is None:
        raise ValueError(f"unknown unit {unit!r}")
    return Fraction(value) / _UNITS[n][2]


def fmt(q: Fraction) -> str:
    """Exact decimal rendering when finite, else a fraction."""
    if q.denominator == 1:
        return str(q.numerator)
    d = q.denominator
    while d % 2 == 0:
        d //= 2
    while d % 5 == 0:
        d //= 5
    if d != 1:
        return f"{q.numerator}/{q.denominator}"
    s, digits = str(abs(q.numerator) * 10**30 // q.denominator), 30
    whole, frac = s[:-digits] or "0", s[-digits:].rstrip("0")
    return ("-" if q < 0 else "") + whole + ("." + frac if frac else "")


def display(value: int, display_unit: str | None, base_unit: str | None) -> str:
    if not display_unit or not base_unit:
        return str(value)
    q = from_base(value, display_unit)
    if normalize_unit(display_unit) == "USD":
        return "$" + (f"{q.numerator}" if q.denominator == 1 else f"{fmt(q)}")
    if normalize_unit(display_unit) == "count":
        return fmt(q)
    return f"{fmt(q)} {display_unit}"


# ---- Span re-parse (regex), used to double-check the numeric extractor -----------------

_SPAN_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
_UNIT_TOKEN = r"(\$|US\$|USD|[A-Za-zµ\"”'¢]+\.?(?:\(A\))?)"
_SIZE_RE = re.compile(r"\b(US|EU|UK)\s*(M(?:en'?s)?|W(?:omen'?s)?)?\s*(?:size\s*)?" + _SPAN_NUM, re.I)
_POST_RE = re.compile(_SPAN_NUM + r"\s*-?\s*" + _UNIT_TOKEN)
_PRE_RE = re.compile(r"(\$|US\$|USD)\s*" + _SPAN_NUM)


def reparse_span(span: str) -> list[tuple[Fraction, str]]:
    """All (number, normalized unit) pairs the regex can read from a span."""
    out: list[tuple[Fraction, str]] = []
    for m in _PRE_RE.finditer(span):
        q = parse_number(m.group(2))
        if q is not None:
            out.append((q, "USD"))
    for m in _SIZE_RE.finditer(span):
        system = m.group(1).upper()
        g = (m.group(2) or "").upper()
        unit = system if system in ("EU", "UK") else ("US_W" if g.startswith("W") else "US_M")
        q = parse_number(m.group(3))
        if q is not None:
            out.append((q, unit))
    for m in _POST_RE.finditer(span):
        u = normalize_unit(m.group(2))
        q = parse_number(m.group(1))
        if u and q is not None:
            out.append((q, u))
    return out


def span_supports(span: str, value: str | int, unit: str) -> bool:
    """True iff the regex re-parse of the span finds exactly this value and unit."""
    q = parse_number(value)
    u = normalize_unit(unit)
    if q is None or u is None:
        return False
    return (q, u) in reparse_span(span)
