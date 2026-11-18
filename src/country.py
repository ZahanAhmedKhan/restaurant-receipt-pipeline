"""Work out which country a receipt comes from, using signs in its OCR text.

"$" and store names (Costco is in Canada, the US, Australia...) don't tell
the country, so we look for things only one country prints:

    Canada:    postal code (L5B 2C9), province + postal code, HST, GST/HST, PST,
               QST/TVQ/TPS, GST/HST business number (123456789 RT0001), CANADA, CAD
    Australia: ABN (11 digits), state + 4-digit postcode (NSW 2000), AUSTRALIA, AUD
    USA:       state + 5-digit ZIP (WA 98027), SALES TAX, USA

Plain "GST" is NOT a Canadian sign: Australia has GST too.
"""

import re

CANADA = "CA"
AUSTRALIA = "AU"
USA = "US"

COUNTRY_NAMES = {CANADA: "Canadian", AUSTRALIA: "Australian", USA: "American"}

# Canadian postal code: letter digit letter, optional space, digit letter digit.
# (D, F, I, O, Q, U are never used; W and Z never come first.)
POSTAL_CODE = r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d"
PROVINCES = r"(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)"
AU_STATES = r"(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT)"
US_STATES = (r"(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
             r"MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)")

# (country, description shown to people, pattern)
SIGNS = [
    (CANADA, "Canadian postal code", re.compile(rf"\b{POSTAL_CODE}\b")),
    (CANADA, "Canadian province", re.compile(rf"\b{PROVINCES}\b\s+{POSTAL_CODE}\b")),
    (CANADA, "HST / GST/HST tax", re.compile(r"\b(?:GST\s*/\s*HST|HST)\b", re.I)),
    (CANADA, "PST / QST tax", re.compile(r"\b(?:PST|QST|TVQ|TPS)\b", re.I)),
    (CANADA, "Canadian business number", re.compile(r"\b\d{9}\s?RT\s?\d{4}\b", re.I)),
    (CANADA, "the word Canada / CAD", re.compile(r"\b(?:CANADA|CAD)\b", re.I)),
    (AUSTRALIA, "Australian business number (ABN)", re.compile(r"\bABN\b", re.I)),
    (AUSTRALIA, "Australian state and postcode", re.compile(rf"\b{AU_STATES}\s+\d{{4}}\b")),
    (AUSTRALIA, "the word Australia / AUD", re.compile(r"\b(?:AUSTRALIA|AUD)\b", re.I)),
    (USA, "US state and ZIP code", re.compile(rf"\b{US_STATES}\s+\d{{5}}(?:-\d{{4}})?\b")),
    (USA, "US sales tax", re.compile(r"\bSALES\s+TAX\b", re.I)),
    (USA, "the word USA", re.compile(r"\b(?:USA|U\.S\.A\.)\b")),
]


def find_signs(text):
    """Return {country: [descriptions of the signs found]}."""
    found = {}
    for country, description, pattern in SIGNS:
        if pattern.search(text or ""):
            found.setdefault(country, []).append(description)
    return found


def detect_country(text):
    """Return (country or None, signs found).

    One country only -> that country. No signs, or signs of several
    countries -> None (a person should look at it).
    """
    signs = find_signs(text)
    if len(signs) == 1:
        return next(iter(signs)), signs
    return None, signs


def describe(signs):
    """Short text for messages, e.g. 'Australian business number (ABN), Australian state and postcode'."""
    parts = []
    for descriptions in signs.values():
        parts.extend(descriptions)
    return ", ".join(parts)
