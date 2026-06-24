"""Pure parsing/normalisation helpers for the Neal's data converter."""
import difflib
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


# --- Org/person name matching -------------------------------------------------
# Used to reconcile the noisy kanban/Bills org names against the canonical
# FreeAgent Contacts sheet (see convert.md §3 / build.resolve_contact). The
# kanban source is hand-typed, so the same real-world business shows up under
# many spellings ('Boxbot'/'BoxBot', 'Apple'/'Apple Inc.'); normalization plus
# fuzzy matching folds them onto one canonical record.

_ORG_SUFFIX_RE = re.compile(
    r'\b(inc|llc|ltd|corp|co|company|corporation|llp|the)\b')

# Tokens that mark a name as a business rather than an individual.
_BUSINESS_TOKENS = {
    'inc', 'llc', 'ltd', 'corp', 'co', 'company', 'corporation', 'llp',
    'studio', 'studios', 'design', 'designs', 'works', 'work', 'lab', 'labs',
    'group', 'services', 'service', 'sign', 'signs', 'signworks', 'fab',
    'fabrication', 'industries', 'productions', 'production', 'machine',
    'machining', 'technology', 'technologies', 'builders', 'building',
    'construction', 'contractors', 'contractor', 'supply', 'architects',
    'architecture', 'metalworks', 'metal', 'woodworks', 'shop', 'systems',
    'solutions', 'enterprises', 'associates', 'assoc', 'partners', 'school',
    'museum', 'dept', 'department', 'university', 'college', 'church', 'fire',
    'city', 'institute', 'foundation', 'council', 'center', 'centre',
    'manufacturing', 'robotics', 'automation', 'electric', 'plastics',
}


def normalize_name(value):
    """Aggressive normalization for matching: lowercase, drop parentheticals,
    strip punctuation, drop common company suffixes, collapse whitespace.
    'Apple Inc.' and 'apple' both -> 'apple'."""
    s = str(value or '').lower().strip()
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = _ORG_SUFFIX_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_display_name(value):
    """Strip a trailing parenthetical annotation from a display name:
    'Creator, Inc. (previously Momentum Machines)' -> 'Creator, Inc.';
    'Milano Technical Group (blacklisted)' -> 'Milano Technical Group'."""
    return re.sub(r'\s*\([^)]*\)\s*$', '', str(value or '').strip()).strip()


def name_similarity(a, b):
    """SequenceMatcher ratio of two names after normalization (0.0-1.0)."""
    return difflib.SequenceMatcher(None, normalize_name(a),
                                   normalize_name(b)).ratio()


def looks_like_person(name):
    """Heuristic: does this name look like an individual, not a business?

    True only for 2-3 alphabetic tokens with no business-y token, no digits,
    and no '&'/'/'/'.com'. 'Alex Tyler' / 'Nicholas R Johnson' -> True;
    'Bridge Design' / 'BWC Architects' / 'B+N Industries' / 'Apple.com' -> False.
    Single-word brand-like names ('Archer') stay False (ambiguous -> business).
    """
    raw = str(name or '').strip()
    if not raw or any(ch.isdigit() for ch in raw):
        return False
    if '&' in raw or '/' in raw or '.com' in raw.lower():
        return False
    toks = re.sub(r"[^A-Za-z .'-]", ' ', raw).split()
    if not (2 <= len(toks) <= 3):
        return False
    if any(t.strip(".'-").lower() in _BUSINESS_TOKENS for t in toks):
        return False
    return all(re.fullmatch(r"[A-Za-z.'-]+", t) for t in toks)


def parse_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = re.sub(r'[^0-9.\-]', '', str(value))
    try:
        return Decimal(cleaned) if cleaned else Decimal('0')
    except InvalidOperation:
        return Decimal('0')


def format_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def format_datetime(value):
    """Like format_date, but returns a timezone-aware (UTC midnight) string
    suitable for a Django DateTimeField under USE_TZ=True. None -> None."""
    d = format_date(value)
    return f'{d}T00:00:00+00:00' if d else None


def to_datetime(value):
    """Parse a cell into a datetime, or None."""
    if isinstance(value, datetime):
        return value
    if value in (None, ''):
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def split_name(full_name):
    if not full_name or not str(full_name).strip():
        return ('(unknown)', '(unknown)')
    parts = str(full_name).strip().split()
    if len(parts) == 1:
        return (parts[0], '(unknown)')
    return (parts[0], ' '.join(parts[1:]))


def revision_parts(reference):
    """('03024b') -> ('03024', 1). Suffix letters a/b/c... -> version index."""
    m = re.match(r'^(\d+)([a-zA-Z]*)$', str(reference).strip())
    if not m:
        return (str(reference).strip(), 0)
    digits, suffix = m.group(1), m.group(2).lower()
    if not suffix:
        return (digits, 0)
    return (digits, ord(suffix[-1]) - ord('a'))


def base_reference(reference):
    """Leading run of digits of a document reference, used as the join key
    between Kanban External IDs and FreeAgent Estimate References.
    '03077-SOLID' -> '03077', '03024b' -> '03024', '07754' -> '07754'.
    Falls back to the stripped string when there are no leading digits."""
    text = str(reference).strip()
    m = re.match(r'(\d+)', text)
    return m.group(1) if m else text


def resolve_li_units_and_qty(item_type, qty):
    """Map a FreeAgent estimate/invoice line's Item Type to canonical
    (units, qty) per apps.core.units.DEFAULT_UNITS.

    The canon list has 'hours' but no 'days', so 'Days' lines are converted
    to 'hours' with qty *= 8 (one workday). 'Hours' passes through as-is.
    Everything else lands on 'none' (the BaseLineItem default) — FreeAgent
    line items carry no other unit signal we can trust.
    """
    it = (item_type or '').strip().lower()
    if it == 'days':
        return ('hours', qty * 8)
    if it == 'hours':
        return ('hours', qty)
    return ('none', qty)


def hours_to_duration(value):
    """'1.5' hours -> Django DurationField string '01:30:00'. '' -> None."""
    if value in (None, ''):
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    total = timedelta(hours=hours)
    s = int(total.total_seconds())
    return f'{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}'


def parse_kanban_name(name):
    """'Business (Contact)' -> ('Business', 'Contact'); 'Business' -> ('Business', None)."""
    m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*$', str(name).strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (str(name).strip(), None)


MATERIAL_KEYWORDS = (
    'plywood', 'acrylic', 'mdf', 'sheet', 'hardwood', 'melamine', 'sintra',
    'aluminum', 'aluminium', 'board feet', 'lumber', 'plastic', 'steel',
    'wood', 'foam', 'gator', 'laminate', 'trupan', 'chipboard', 'baltic birch',
)
COUNT_UNITS = ('each', 'ea', 'pcs', 'pieces', 'unit', 'units')


def classify_line_item(item_type, description):
    """Return one of: 'skip', 'task', 'material', 'lineitem'."""
    it = (item_type or '').strip().lower()
    if it == 'comment':
        return 'skip'
    if it in ('discount', 'credit'):
        return 'lineitem'
    # A line item describing a cut operation is always labour, never a
    # material — even if its Item Type or keywords would say otherwise.
    if (description or '').strip().lower().startswith('cut'):
        return 'task'
    if it in ('hours', 'days', 'services'):
        return 'task'
    if it in ('products', 'expenses'):
        return 'material'
    # '-no unit-' and anything unrecognised: keyword heuristic
    desc = (description or '').lower()
    if any(kw in desc for kw in MATERIAL_KEYWORDS):
        return 'material'
    return 'task'


def parse_checklist(cell):
    """Parse a Kanban 'Checklist' cell into ordered task entries.

    Each non-blank line looks like '[ ] text' (unchecked) or '[X] text'
    (checked). A line with leading whitespace is a subtask of the most
    recent non-indented line. Lines may carry a trailing ';'.
    Returns a list of dicts: {'text': str, 'completed': bool,
    'is_subtask': bool}.
    """
    items = []
    for raw in (cell or '').splitlines():
        if not raw.strip():
            continue
        is_subtask = raw[:1] in (' ', '\t')
        line = raw.strip().rstrip(';').strip()
        m = re.match(r'^\[\s*([xX]?)\s*\]\s*(.*)$', line)
        if not m:
            continue
        text = m.group(2).strip().rstrip(';').strip()
        if not text:
            continue
        items.append({
            'text': text,
            'completed': bool(m.group(1)),
            'is_subtask': is_subtask,
        })
    return items


def checklist_scheme_name(task_name):
    """ServicePrice name for a task, chosen by keyword in its name.

    Starts with 'cut' -> 'CNC routing'; contains 'laser' -> 'Laser';
    contains 'draw'/'cad'/'model' -> 'CAD'; otherwise -> 'Shop labor'.
    """
    n = (task_name or '').strip().lower()
    if n.startswith('cut'):
        return 'CNC routing'
    if 'laser' in n:
        return 'Laser'
    if 'draw' in n or 'cad' in n or 'model' in n:
        return 'CAD'
    return 'Shop labor'


def infer_algorithm(item_type, units):
    """ServicePrice.algorithm for a Task-classified line item."""
    it = (item_type or '').strip().lower()
    u = (units or '').strip().lower()
    if it in ('hours', 'days') or u in ('hour', 'hours', 'day', 'days'):
        return 'elapsed_time'
    if u in COUNT_UNITS:
        return 'entered_qty'
    return 'flat_fee'


# --- Synthetic-value helpers (worker times, actuals, blep lengths) -----------

# Multipliers applied on a deterministic index % 3 rotation: exactly one third
# exact, one third +10%, one third −5%. Used for blep lengths (vs est_worker_time),
# entered_qty actuals (vs est_qty), and anywhere the "thirds rule" applies.
_THIRDS = (Decimal('1.0'), Decimal('1.10'), Decimal('0.95'))


def thirds_factor(index):
    """Return the thirds-rule multiplier (Decimal) for a 0-based index."""
    return _THIRDS[index % 3]


def round_2sig(value):
    """Round a positive float to 2 significant figures.

    For values in [0.5, 4.0] this yields 2 decimals below 1.0 (e.g. 0.55) and
    1 decimal at/above 1.0 (e.g. 1.2, 3.8) — i.e. "up to 2 significant digits".
    """
    if value <= 0:
        return 0.0
    digits = 2 - int(math.floor(math.log10(abs(value)))) - 1
    return round(value, digits)


def parse_duration(value):
    """Parse a Django DurationField 'HH:MM:SS' string into a timedelta. None-safe."""
    if not value:
        return None
    parts = str(value).split(':')
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return timedelta(hours=h, minutes=m, seconds=s)


# --- Material → PriceListItem fuzzy matching ---------------------------------

# Material families: a keyword (or multiword phrase) that may appear in both an
# estimate line description and a PriceListItem description. Multiword phrases
# are checked before single words so 'baltic birch' wins over bare 'birch'.
_PLI_MATERIAL_KEYWORDS = (
    'baltic birch', 'apple ply', 'appleply', 'external grade',
    'shop maple', 'shop ply', 'shop plywood', 'pressure treated',
    'acrylic', 'aluminum', 'aluminium', 'sintra', 'melamine', 'mdf',
    'plywood', 'luan', 'sapele', 'walnut', 'maple', 'oak', 'birch',
    'abs', 'acm', 'laminate', 'polycarbonate', 'pvc', 'hdpe', 'foam',
)

# Thickness tokens → normalised decimal-inch string. Fractions and decimals in
# inches both reduce to the same key so '3/4"' matches a PLI coded '.75'.
_FRACTION_RE = re.compile(r'(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})\s*(?:"|in\b|inch)?')
_DECIMAL_IN_RE = re.compile(r'(?<![\d/])(\d?\.\d{1,3}|\d{1,2})\s*"')


def _normalise_thickness_token(num):
    """Round an inch measure to 3 dp and strip trailing zeros: 0.750 -> '0.75'."""
    q = Decimal(str(num)).quantize(Decimal('0.001'))
    s = format(q.normalize(), 'f')
    return s


def extract_thicknesses(text):
    """Return the set of normalised decimal-inch thickness keys found in text.

    Recognises fractions ('3/4"', '1/8') and decimal inches ('.125', '1"').
    Plain integers without a quote are ignored unless quoted, to avoid matching
    counts/dimensions ('5 sheets', '48" x 96"' — the 48/96 are quoted but large,
    so a sanity cap of < 3 inches keeps only plausible material thicknesses).
    """
    found = set()
    for m in _FRACTION_RE.finditer(text):
        num, den = int(m.group(1)), int(m.group(2))
        if den == 0:
            continue
        val = num / den
        if 0 < val <= 3:
            found.add(_normalise_thickness_token(val))
    for m in _DECIMAL_IN_RE.finditer(text):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        if 0 < val <= 3:
            found.add(_normalise_thickness_token(val))
    return found


def _material_keywords(text):
    """Return the set of material family keywords present in text (lowercased)."""
    t = (text or '').lower()
    return {kw for kw in _PLI_MATERIAL_KEYWORDS if kw in t}


def match_pli(description, pli_index):
    """Fuzzy-match a material description to a PriceListItem code.

    ``pli_index`` is a list of {'code', 'description'} dicts. A match requires a
    shared material-family keyword AND an equal thickness. Among candidates, the
    one with the most keyword overlap wins (ties broken by shortest then
    lexically-smallest code, for determinism). Returns the matched code, or None.

    Precision over recall: prose with no thickness, or a material family absent
    from the price list, yields None — an acceptable miss.
    """
    desc_kws = _material_keywords(description)
    desc_th = extract_thicknesses(description or '')
    if not desc_kws or not desc_th:
        return None

    candidates = []
    for row in pli_index:
        code = (row.get('code') or '').strip()
        if not code:
            continue
        pli_desc = row.get('description') or ''
        shared = desc_kws & _material_keywords(pli_desc)
        if not shared:
            continue
        pli_th = extract_thicknesses(pli_desc) | extract_thicknesses(code)
        if not (desc_th & pli_th):
            continue
        candidates.append((len(shared), code))
    if not candidates:
        return None
    # Most keyword overlap wins; ties → shortest code, then lexically smallest.
    candidates.sort(key=lambda c: (-c[0], len(c[1]), c[1]))
    return candidates[0][1]
